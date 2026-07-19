"""
Binary Arbitrage Strategy — buys YES + NO when pair_cost < $1.00.

When a PriceUpdateEvent with _arb_data.type == "binary" arrives:
  1. Calculate position sizes based on available liquidity
  2. Execute both legs in batch (same tick)
  3. Hold until resolution or stop-loss

Guaranteed profit = $1.00 - pair_cost (minus fees) per pair.
"""

import asyncio
import os
import time
from src.strategy.base import BaseStrategy
from src.events import PriceUpdateEvent, SignalEvent


class BinaryArbitrageStrategy(BaseStrategy):
    def __init__(
        self,
        symbol: str,
        position_size_usd: float = 50.0,
        min_net_spread: float = 0.01,
        max_hold_seconds: float = 900,
        stop_loss_usd: float = 15.0,
        fee_rate: float = 0.02,
        db=None,
        worker_id: str = "worker_2",
    ):
        super().__init__(symbol)
        self.position_size_usd = float(
            os.getenv("BINARY_ARB_POSITION_SIZE_USD", str(position_size_usd))
        )
        self.min_net_spread = float(
            os.getenv("BINARY_ARB_MIN_SPREAD", str(min_net_spread))
        )
        self.max_hold_seconds = float(
            os.getenv("BINARY_ARB_MAX_HOLD", str(max_hold_seconds))
        )
        self.stop_loss_usd = float(
            os.getenv("BINARY_ARB_STOP_LOSS_USD", str(stop_loss_usd))
        )
        self.fee_rate = float(
            os.getenv("BINARY_ARB_FEE_RATE", str(fee_rate))
        )
        self.db = db
        self.worker_id = worker_id

        self.last_position = None
        self.entry_price = 0.0
        self.entry_time = 0.0
        self._position_id = None
        self._arb_position = None
        self.last_arbitrage_opportunity = None
        self.edge = 0.0
        self.teorical_probability = 0.5
        self.kelly_recommendation = 0.0

        self._peak_profit = 0.0
        self._breakeven_activated = False
        self._pending_signals = []

    def on_price_update(self, event: PriceUpdateEvent):
        super().on_price_update(event)

        arb_data = getattr(event, "_arb_data", None)
        if arb_data is None or arb_data.get("type") != "binary":
            return None

        pair_cost = arb_data["pair_cost"]
        net_spread = arb_data["net_spread"]
        yes_ask = arb_data["yes_ask"]
        no_ask = arb_data["no_ask"]
        yes_size = arb_data["yes_size"]
        no_size = arb_data["no_size"]
        title = arb_data["title"]
        slug = arb_data["slug"]

        self.last_arbitrage_opportunity = {
            "pair_cost": pair_cost,
            "net_spread": net_spread,
            "yes_ask": yes_ask,
            "no_ask": no_ask,
            "title": title,
        }
        self.edge = net_spread
        self.teorical_probability = yes_ask

        if self.last_position is not None:
            return self._evaluate_hold(event)

        if net_spread < self.min_net_spread:
            return None

        shares = int(self.position_size_usd / pair_cost)
        if shares < 1:
            return None

        if self.db:
            balances = {
                item["asset"]: float(item["free_balance"])
                for item in self.db.get_portfolio(self.worker_id)
            }
            available = balances.get("USD", 0.0)
            if available < self.position_size_usd:
                return None

        expected_profit = shares * net_spread

        self._arb_position = {
            "slug": slug,
            "title": title,
            "yes_ask": yes_ask,
            "no_ask": no_ask,
            "pair_cost": pair_cost,
            "shares": shares,
            "expected_profit": expected_profit,
            "entry_time": asyncio.get_event_loop().time(),
        }

        self.last_position = "BINARY_ARB"
        self.entry_price = pair_cost
        self.entry_time = asyncio.get_event_loop().time()

        if self.db:
            self._position_id = self.db.save_position(
                self.worker_id,
                f"binary_{slug}",
                "BUY",
                pair_cost,
                expected_profit,
            )

        reason = (
            f"Binary Arb: YES@{yes_ask:.4f} + NO@{no_ask:.4f} = "
            f"{pair_cost:.4f} | Net: {net_spread:+.4f} | "
            f"Shares: {shares} | Expected: ${expected_profit:.4f}"
        )

        if self.db:
            self.db.log("INFO", f"[Binary Arb] {reason}", self.worker_id)

        self._pending_signals = [
            SignalEvent(
                symbol=f"binary_{slug}_YES",
                side="BUY",
                price=yes_ask,
                reason=f"[{shares}] BUY YES @ {yes_ask:.4f} ({title})",
                amount=float(shares) * yes_ask,
                position_id=self._position_id,
            ),
            SignalEvent(
                symbol=f"binary_{slug}_NO",
                side="BUY",
                price=no_ask,
                reason=f"[{shares}] BUY NO @ {no_ask:.4f} ({title})",
                amount=float(shares) * no_ask,
                position_id=self._position_id,
            ),
        ]

        return self._pending_signals.pop(0)

    def _evaluate_hold(self, event: PriceUpdateEvent):
        if self._arb_position is None:
            return None

        now = asyncio.get_event_loop().time()
        elapsed = now - self._arb_position["entry_time"]

        current_pair = event.price
        entry_pair = self._arb_position["pair_cost"]
        shares = self._arb_position["shares"]
        pnl = shares * (1.0 - current_pair) - shares * (1.0 - entry_pair)

        self._peak_profit = max(self._peak_profit, pnl)

        if not self._breakeven_activated and pnl > 0:
            self._breakeven_activated = True

        if self._breakeven_activated and pnl < -0.001:
            return self._close("Breakeven stop")

        if pnl < -self.stop_loss_usd:
            return self._close(f"Stop Loss (${pnl:.2f})")

        if elapsed >= self.max_hold_seconds:
            return self._close(f"Time Stop ({elapsed:.0f}s)")

        return None

    def evaluate_signal(self, event: PriceUpdateEvent):
        return None

    def _close(self, reason: str):
        arb = self._arb_position
        if arb is None:
            return None

        shares = arb["shares"]
        entry_pair = arb["pair_cost"]
        expected_profit = arb.get("expected_profit", 0)

        self._arb_position = None
        self.last_position = None
        self._breakeven_activated = False
        self._peak_profit = 0.0

        if self.db and self._position_id:
            self.db.close_position(
                self._position_id,
                entry_pair,
                f"Binary Arb {reason}",
            )

        slug = arb["slug"]

        return SignalEvent(
            symbol=f"binary_{slug}_YES",
            side="SELL",
            price=0.0,
            reason=f"Binary Arb close: {reason} | Expected profit: ${expected_profit:.4f}",
            amount=float(shares),
            position_id=self._position_id,
        )
