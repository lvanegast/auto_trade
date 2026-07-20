"""
Oracle Momentum Strategy — trades binary "Up or Down" markets on Limitless
when real-time crypto momentum diverges from market-implied probability.

Buys YES when crypto is trending UP and YES is cheap.
Buys NO when crypto is trending DOWN and NO is cheap.
Holds until resolution (win = $1.00, lose = $0.00).
"""

import asyncio
import os
import time
from src.strategy.base import BaseStrategy
from src.events import PriceUpdateEvent, SignalEvent


class OracleMomentumStrategy(BaseStrategy):
    def __init__(
        self,
        symbol: str,
        position_size_usd: float = 50.0,
        stop_loss_pct: float = 0.40,
        max_hold_seconds: float = 900,
        db=None,
        worker_id: str = "worker_4",
    ):
        super().__init__(symbol)
        self.position_size_usd = float(
            os.getenv("ORACLE_POSITION_SIZE_USD", str(position_size_usd))
        )
        self.stop_loss_pct = float(
            os.getenv("ORACLE_STOP_LOSS_PCT", str(stop_loss_pct))
        )
        self.max_hold_seconds = float(
            os.getenv("ORACLE_MAX_HOLD", str(max_hold_seconds))
        )
        self.min_edge = float(os.getenv("ORACLE_MIN_EDGE_PCT", "0.08"))
        self.min_confidence = float(os.getenv("ORACLE_MIN_CONFIDENCE", "0.30"))
        self.db = db
        self.worker_id = worker_id

        self._current_signal = None
        self._entry_time = 0.0
        self._entry_price = 0.0
        self._position_id = None
        self._pending_signals = []

    def on_price_update(self, event: PriceUpdateEvent):
        super().on_price_update(event)

        arb_data = getattr(event, "_arb_data", None)
        if arb_data is None or arb_data.get("type") != "oracle_momentum":
            return None

        if self._current_signal is not None:
            return self._check_exit(event, arb_data)

        signal = arb_data["signal"]
        edge = arb_data["edge"]
        confidence = arb_data["confidence"]
        side = arb_data["side"]
        market_price = arb_data["market_price"]
        title = arb_data["title"]
        slug = arb_data["slug"]
        pct_change = arb_data["pct_change"]
        expires_at = arb_data.get("expires_at", 0)

        now = time.time()
        if expires_at > 0:
            ttl = expires_at - now
            if ttl < 30:
                return None
            if ttl > 600:
                return None

        if edge < self.min_edge:
            return None
        if confidence < self.min_confidence:
            return None

        if self.db:
            balances = {
                item["asset"]: float(item["free_balance"])
                for item in self.db.get_portfolio(self.worker_id)
            }
            available = balances.get("USD", 0.0)
            if available < self.position_size_usd:
                return None

        shares = int(self.position_size_usd / market_price)
        if shares < 1:
            return None

        expected_profit = shares * edge

        self._current_signal = {
            "slug": slug,
            "title": title,
            "side": side,
            "signal": signal,
            "market_price": market_price,
            "edge": edge,
            "confidence": confidence,
            "shares": shares,
            "pct_change": pct_change,
            "entry_time": asyncio.get_event_loop().time(),
            "expected_profit": expected_profit,
        }
        self._entry_time = asyncio.get_event_loop().time()
        self._entry_price = market_price

        reason = (
            f"Oracle Momentum: {side} @ {market_price:.4f} | "
            f"Momentum: {pct_change:+.3f}% | Edge: {edge:+.4f} | "
            f"Shares: {shares} | Expected: ${expected_profit:.2f}"
        )

        if self.db:
            self.db.log("INFO", f"[Oracle] {reason}", self.worker_id)

        print(f"[Oracle Strategy] ENTRY: {reason}")

        self._pending_signals = [
            SignalEvent(
                symbol=f"oracle_{slug}_{side}",
                side="BUY",
                price=market_price,
                reason=f"[{shares}] BUY {side} @ {market_price:.4f} ({title})",
                amount=float(shares),
                position_id=self._position_id,
            ),
        ]

        return self._pending_signals.pop(0)

    def _check_exit(self, event: PriceUpdateEvent, arb_data: dict):
        if self._current_signal is None:
            return None

        now = asyncio.get_event_loop().time()
        elapsed = now - self._current_signal["entry_time"]

        side = self._current_signal["side"]
        entry_price = self._current_signal["market_price"]
        self._current_signal["slug"]
        self._current_signal["title"]
        shares = self._current_signal["shares"]

        current_price = arb_data["yes_price"] if side == "YES" else arb_data["no_price"]
        shares * (current_price - entry_price)

        if current_price >= 0.95:
            return self._close(
                f"Near resolution (${current_price:.2f})",
                sell_price=1.0,
            )

        if elapsed >= self.max_hold_seconds:
            return self._close(
                f"Time Stop ({elapsed:.0f}s)",
                sell_price=current_price,
            )

        if entry_price > 0:
            loss_pct = (entry_price - current_price) / entry_price
            if loss_pct >= self.stop_loss_pct:
                return self._close(
                    f"Stop Loss ({loss_pct * 100:.1f}%)",
                    sell_price=current_price,
                )

        if arb_data.get("expires_at", 0) > 0:
            ttl = arb_data["expires_at"] - time.time()
            if ttl <= 0:
                return self._close(
                    "Market expired",
                    sell_price=current_price,
                )

        return None

    def _close(self, reason: str, sell_price: float = 0.0):
        sig = self._current_signal
        if sig is None:
            return None

        side = sig["side"]
        slug = sig["slug"]
        shares = sig["shares"]
        entry_price = sig["market_price"]
        sig.get("expected_profit", 0)

        self._current_signal = None
        self._position_id = None

        if sell_price <= 0:
            sell_price = 0.0

        payout = shares * sell_price
        cost = shares * entry_price
        actual_profit = payout - cost

        if self.db:
            self.db.log(
                "INFO",
                f"Oracle cerrado: {reason} | {side} | "
                f"Entry: {entry_price:.4f} → Exit: {sell_price:.4f} | "
                f"Payout: ${payout:.2f} | Cost: ${cost:.2f} | "
                f"Profit: ${actual_profit:.2f}",
                self.worker_id,
            )

        close_reason = (
            f"Oracle close: {reason} | {side} | "
            f"Entry: {entry_price:.4f} → Exit: {sell_price:.4f} | "
            f"Profit: ${actual_profit:.2f}"
        )

        print(f"[Oracle Strategy] EXIT: {close_reason}")

        self._pending_signals = [
            SignalEvent(
                symbol=f"oracle_{slug}_{side}",
                side="SELL",
                price=sell_price,
                reason=close_reason,
                amount=float(shares),
                position_id=None,
            ),
        ]

        return self._pending_signals.pop(0)

    def evaluate_signal(self, event: PriceUpdateEvent):
        return None
