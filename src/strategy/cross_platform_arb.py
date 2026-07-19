"""
Cross-Platform Arbitrage Strategy — dual mode.

Mode 1 (Cross-Platform): When both Kalshi and Limitless have the same event,
buy YES on the cheaper + buy NO on the other. Guaranteed profit = $1 - total_cost.

Mode 2 (1×N Intra-Platform): When only Limitless is available, detect group
markets where sum(YES) != 1.0 and buy ALL outcomes.
  sum(YES) < 1.0 → buy all YES → profit = $1 - sum(YES)
  sum(YES) > 1.0 → buy all NO → profit = sum(YES) - $1

Mode is auto-detected: if CrossPlatformTracker has both platforms → cross-platform.
If only one platform → 1×N.
"""

import asyncio
import os
from src.strategy.base import BaseStrategy
from src.strategy.cross_platform_tracker import cross_platform_tracker
from src.strategy.market_pairs import (
    get_pair_by_kalshi_ticker,
    get_pair_by_limitless_slug,
)
from src.events import PriceUpdateEvent, SignalEvent


class CrossPlatformArbitrageStrategy(BaseStrategy):
    def __init__(
        self,
        symbol: str,
        feeder_type: str = "kalshi",
        min_edge_pct: float = 0.03,
        position_size_pct: float = 0.5,
        position_size_usd: float = None,
        max_hold_seconds: float = 120.0,
        stop_loss_pct: float = 0.05,
        stop_loss_usd: float = None,
        take_profit_pct: float = 0.08,
        cooldown_seconds: float = 10.0,
        db=None,
        worker_id: str = "worker_2",
    ):
        super().__init__(symbol)
        self.feeder_type = feeder_type.lower()
        self.min_edge_pct = min_edge_pct
        self.position_size_pct = position_size_pct
        self.position_size_usd = float(
            os.getenv("CROSS_ARB_POSITION_SIZE_USD", str(position_size_usd if position_size_usd is not None else 50.0))
        )
        self.max_hold_seconds = float(
            os.getenv("CROSS_ARB_MAX_HOLD_SECONDS", str(max_hold_seconds))
        )
        self.stop_loss_pct = float(
            os.getenv("CROSS_ARB_STOP_LOSS_PCT", str(stop_loss_pct))
        )
        self.stop_loss_usd = float(
            os.getenv("CROSS_ARB_STOP_LOSS_USD", str(stop_loss_usd if stop_loss_usd is not None else 15.0))
        )
        self.take_profit_pct = float(
            os.getenv("CROSS_ARB_TAKE_PROFIT_PCT", str(take_profit_pct))
        )
        self.cooldown_seconds = float(
            os.getenv("CROSS_ARB_COOLDOWN_SECONDS", str(cooldown_seconds))
        )
        self.db = db
        self.worker_id = worker_id
        self._position_id = None
        self._tracker = cross_platform_tracker

        self.event_id = self._resolve_event_id()

        # Cross-platform state
        self.last_position = None
        self.entry_price = 0.0
        self.entry_time = None
        self.last_exit_time = 0.0
        self.last_arbitrage_opportunity = None
        self._peak_profit = 0.0
        self._breakeven_activated = False

        # 1×N state
        self._arb_groups = {}
        self._pending_signals = []
        self._last_exit_time = {}

        self.teorical_probability = 0.50
        self.edge = 0.0
        self.kelly_recommendation = 0.0
        self.mode = "cross_platform"  # or "1xN"

    def _resolve_event_id(self) -> str | None:
        """Resuelve el event_id lógico a partir del ticker/token del feeder."""
        if self.feeder_type == "kalshi":
            pair = get_pair_by_kalshi_ticker(self.symbol)
            return pair["event_id"] if pair else None
        elif self.feeder_type == "limitless":
            pair = get_pair_by_limitless_slug(self.symbol)
            return pair["event_id"] if pair else None
        return None

    def on_price_update(self, event: PriceUpdateEvent) -> SignalEvent:
        """Procesa cada tick: cross-platform arb o 1×N intra-platform."""
        super().on_price_update(event)

        # Drain pending 1×N signals
        if self._pending_signals:
            return self._pending_signals.pop(0)

        current_price = event.price
        self.teorical_probability = current_price

        # Check if we have cross-platform data
        if self.event_id:
            both = self._tracker.get_both_prices(self.event_id)
            has_kalshi = both.get("kalshi", {}).get("price", 0) > 0
            has_limitless = both.get("limitless", {}).get("price", 0) > 0

            if has_kalshi and has_limitless:
                self.mode = "cross_platform"
                return self._handle_cross_platform(event, current_price)

        # Fallback: 1×N intra-platform on Limitless macro group markets
        self.mode = "1xN"
        return self._handle_1xN(event, current_price)

    def _handle_cross_platform(self, event: PriceUpdateEvent, current_price: float) -> SignalEvent:
        """Original cross-platform arbitrage logic."""
        # Update tracker with our price
        self._tracker.update_price(
            event_id=self.event_id,
            platform=self.feeder_type,
            price=current_price,
            bid=event.bid,
            ask=event.ask,
        )

        # If we have an open position, evaluate exit
        if self.last_position is not None:
            return self._evaluate_exit(current_price)

        # Cooldown
        now = asyncio.get_event_loop().time()
        if now - self.last_exit_time < self.cooldown_seconds:
            return None

        # Calculate arbitrage
        opp = self._tracker.calculate_arbitrage(
            self.event_id, min_edge_pct=self.min_edge_pct
        )

        if opp is None:
            self.edge = 0.0
            self.kelly_recommendation = 0.0
            self.last_arbitrage_opportunity = None
            return None

        self.last_arbitrage_opportunity = opp
        self.edge = opp["edge_pct"]

        if opp["buy_platform"] != self.feeder_type:
            self.kelly_recommendation = 0.0
            return None

        # Kelly sizing
        cost = opp["total_cost"]
        if cost > 0 and cost < 1.0:
            self.kelly_recommendation = self.position_size_pct * (opp["edge_pct"] / cost)
        else:
            self.kelly_recommendation = 0.0

        if self.kelly_recommendation > 0.01:
            self.last_position = "BUY"
            self.entry_price = current_price
            self.entry_time = asyncio.get_event_loop().time()

            if self.db:
                self._position_id = self.db.save_position(
                    self.worker_id,
                    self.symbol,
                    "BUY",
                    current_price,
                    opp["limitless_yes"] if self.feeder_type == "kalshi" else opp["kalshi_yes"],
                )

            reason = (
                f"Cross-Platform Arb: "
                f"YES @{self.feeder_type.upper()}={current_price:.4f} | "
                f"Edge: {opp['edge_pct']:.2%} | "
                f"Cost: {cost:.4f} | Profit: {opp['guaranteed_profit']:.4f}"
            )

            if self.db:
                self.db.log("INFO", f"[Cross-Arb] {reason}", self.worker_id)

            return SignalEvent(
                symbol=self.symbol,
                side="BUY",
                price=current_price,
                reason=reason,
                amount=self.kelly_recommendation,
                position_id=self._position_id,
            )

        return None

    def _handle_1xN(self, event: PriceUpdateEvent, current_price: float) -> SignalEvent:
        """1×N intra-platform arb on Limitless macro group markets."""
        event_id = event.symbol

        # Check exit for active groups
        if event_id in self._arb_groups:
            return self._evaluate_group_exit(event_id, current_price)

        # Cooldown
        now = asyncio.get_event_loop().time()
        if event_id in self._last_exit_time:
            if now - self._last_exit_time[event_id] < self.cooldown_seconds:
                return None

        # Read macro edge data from feeder
        from src.feeders.limitless_feeder import get_macro_edge_data
        macro_data = get_macro_edge_data()

        edge_data = macro_data.get(event_id)
        if edge_data is None:
            return None

        total_yes = edge_data["total_yes"]
        edge = edge_data["edge"]
        outcomes = edge_data.get("outcomes", [])
        title = edge_data.get("title", event_id)

        if abs(edge) < self.min_edge_pct or len(outcomes) < 2:
            return None

        if event_id in self._arb_groups:
            return None

        # Determine arb type
        arb_type = "YES" if edge > 0 else "NO"

        # Calculate 1×N
        total_cost = 0.0
        per_outcome_signals = []

        if arb_type == "YES":
            for outcome in outcomes:
                yes_price = outcome["yes_price"]
                total_cost += yes_price
                per_outcome_signals.append({
                    "slug": outcome["slug"],
                    "title": outcome["title"],
                    "side": "BUY",
                    "token": "YES",
                    "price": yes_price,
                })
        else:
            for outcome in outcomes:
                no_price = outcome["no_price"]
                total_cost += no_price
                per_outcome_signals.append({
                    "slug": outcome["slug"],
                    "title": outcome["title"],
                    "side": "BUY",
                    "token": "NO",
                    "price": no_price,
                })

        expected_profit = 1.0 - total_cost if arb_type == "YES" else total_cost - 1.0
        if expected_profit <= 0:
            return None

        per_outcome_amount = self.position_size_usd / len(outcomes)
        total_spend = per_outcome_amount * len(outcomes)

        # Check balance
        if self.db:
            balances = {
                item["asset"]: float(item["free_balance"])
                for item in self.db.get_portfolio(self.worker_id)
            }
            available = balances.get("USD", 0.0)
            if available < total_spend:
                return None

        # Record arb group
        self._arb_groups[event_id] = {
            "entry_time": now,
            "total_cost": total_cost,
            "expected_profit": expected_profit,
            "arb_type": arb_type,
            "outcomes": outcomes,
            "title": title,
            "position_ids": [],
        }

        # Generate N sequential BUY signals
        signals = []
        for i, sig_data in enumerate(per_outcome_signals):
            position_id = None
            if self.db:
                position_id = self.db.save_position(
                    self.worker_id,
                    f"{event_id}_{sig_data['slug']}",
                    "BUY",
                    sig_data["price"],
                )
                self._arb_groups[event_id]["position_ids"].append(position_id)

            reason = (
                f"1x{len(outcomes)} {arb_type} Arb [{i+1}/{len(outcomes)}]: "
                f"{title} | {sig_data['title']} | "
                f"{sig_data['token']} @{sig_data['price']:.4f} | "
                f"Total: ${total_cost:.4f} | Profit: ${expected_profit:.4f}"
            )

            signals.append(SignalEvent(
                symbol=f"{event_id}_{sig_data['slug']}",
                side="BUY",
                price=sig_data["price"],
                reason=reason,
                amount=per_outcome_amount,
                position_id=position_id,
            ))

        if self.db:
            self.db.log(
                "INFO",
                f"[Macro 1xN {arb_type}] {title} | "
                f"Cost: ${total_cost:.4f} | Profit: ${expected_profit:.4f} | "
                f"{len(outcomes)} outcomes x ${per_outcome_amount:.2f}",
                self.worker_id,
            )

        if len(signals) > 1:
            self._pending_signals = signals[1:]
        return signals[0]

    def _evaluate_exit(self, current_price: float) -> SignalEvent:
        """Exit cross-platform position."""
        now = asyncio.get_event_loop().time()
        elapsed = now - self.entry_time

        profit_pct = (current_price - self.entry_price) / self.entry_price
        self._peak_profit = max(self._peak_profit, profit_pct)

        if not self._breakeven_activated and profit_pct >= self.take_profit_pct * 0.3:
            self._breakeven_activated = True

        if self.take_profit_pct > 0 and profit_pct >= self.take_profit_pct:
            return self._trigger_exit("SELL", current_price,
                f"Take Profit ({profit_pct:+.2%}). Hold: {elapsed:.1f}s")

        if self._breakeven_activated:
            drawdown = self._peak_profit - profit_pct
            if drawdown >= 0.005:
                return self._trigger_exit("SELL", current_price,
                    f"Trailing Stop: {self._peak_profit:+.2%} -> {profit_pct:+.2%}. Hold: {elapsed:.1f}s")

        if self.stop_loss_usd > 0 and profit_pct < 0:
            loss_usd = abs(profit_pct) * self.position_size_pct * self.entry_price
            if loss_usd >= self.stop_loss_usd:
                return self._trigger_exit("SELL", current_price,
                    f"Stop Loss USD (${loss_usd:.2f}). Hold: {elapsed:.1f}s")

        if self.stop_loss_pct > 0 and profit_pct <= -self.stop_loss_pct:
            return self._trigger_exit("SELL", current_price,
                f"Stop Loss ({profit_pct:+.2%}). Hold: {elapsed:.1f}s")

        if elapsed >= self.max_hold_seconds:
            return self._trigger_exit("SELL", current_price,
                f"Time Stop ({elapsed:.1f}s). PnL: {profit_pct:+.2%}")

        if self.last_arbitrage_opportunity:
            opp = self._tracker.calculate_arbitrage(self.event_id, min_edge_pct=self.min_edge_pct)
            if opp is None:
                return self._trigger_exit("SELL", current_price,
                    f"Arb closed. PnL: {profit_pct:+.2%}")

        return None

    def _evaluate_group_exit(self, event_id: str, current_price: float) -> SignalEvent:
        """Exit 1×N arb group."""
        group = self._arb_groups.get(event_id)
        if not group:
            return None

        now = asyncio.get_event_loop().time()
        elapsed = now - group["entry_time"]

        if elapsed >= self.max_hold_seconds:
            return self._close_group(event_id, f"Time Stop ({elapsed:.0f}s)")

        return None

    def _close_group(self, event_id: str, reason: str) -> SignalEvent:
        """Close all outcomes in a 1×N group."""
        group = self._arb_groups.pop(event_id, None)
        if not group:
            return None

        self._last_exit_time[event_id] = asyncio.get_event_loop().time()

        arb_type = group["arb_type"]
        outcomes = group["outcomes"]
        expected_profit = group["expected_profit"]
        title = group["title"]

        for pos_id in group.get("position_ids", []):
            if self.db and pos_id:
                self.db.close_position(pos_id, 0.0, f"1xN {arb_type} closed: {reason}", worker_id=self.worker_id)

        from src.security import security_guard
        security_guard.record_pnl(self.worker_id, expected_profit)

        if self.db:
            self.db.log("INFO", f"[Macro 1xN CLOSE] {title} | Profit: ${expected_profit:.4f} | {reason}", self.worker_id)

        per_outcome_amount = self.position_size_usd / len(outcomes)
        signals = []
        for i, outcome in enumerate(outcomes):
            sell_price = outcome["yes_price"] if arb_type == "YES" else outcome["no_price"]
            position_id = group.get("position_ids", [None])[i] if i < len(group.get("position_ids", [])) else None
            signals.append(SignalEvent(
                symbol=f"{event_id}_{outcome['slug']}",
                side="SELL",
                price=sell_price,
                reason=f"1xN {arb_type} exit: {reason}",
                amount=per_outcome_amount,
                position_id=position_id,
            ))

        if signals:
            if len(signals) > 1:
                self._pending_signals = signals[1:]
            return signals[0]

        return None

    def _trigger_exit(self, side: str, price: float, reason: str) -> SignalEvent:
        """Close cross-platform position."""
        closed_position_id = self._position_id
        self.last_exit_time = asyncio.get_event_loop().time()

        if self.last_position == "BUY":
            pnl = (price - self.entry_price) * self.position_size_pct
        elif self.last_position == "SELL":
            pnl = (self.entry_price - price) * self.position_size_pct
        else:
            pnl = 0.0

        if self._position_id and self.db:
            self.db.close_position(self._position_id, price, reason, worker_id=self.worker_id)

        from src.security import security_guard
        security_guard.record_pnl(self.worker_id, pnl)

        self.last_position = None
        self.entry_price = 0.0
        self.entry_time = None
        self._position_id = None
        self._peak_profit = 0.0
        self._breakeven_activated = False

        if self.db:
            self.db.log("INFO", f"[Cross-Arb] Cierre: {reason}", self.worker_id)

        return SignalEvent(
            symbol=self.symbol,
            side=side,
            price=price,
            reason=reason,
            amount=self.position_size_pct,
            position_id=closed_position_id,
        )

    def evaluate_signal(self, event: PriceUpdateEvent) -> SignalEvent:
        return None
