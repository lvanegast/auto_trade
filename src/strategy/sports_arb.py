"""
Sports Arbitrage Strategy — intra-platform arb on Limitless Exchange.

Detects group markets (Method of Victory, Player of the Match, etc.)
where the sum of all YES outcomes deviates from 1.0.

  sum(YES) < 1.0  →  buy all outcomes = guaranteed profit
  sum(YES) > 1.0  →  overpriced (sell if holding)

Edge data is written by LimitlessSportsFeeder into _sports_edge_data,
and read here on each PriceUpdateEvent.
"""

import asyncio
import os
from src.strategy.base import BaseStrategy
from src.events import PriceUpdateEvent, SignalEvent

# Shared data store: feeder writes, strategy reads
# {event_id: {"total_yes": float, "edge": float, "outcomes_count": int, "title": str}}
_sports_edge_data: dict = {}


def update_sports_edge(event_id: str, total_yes: float, edge: float, outcomes_count: int, title: str = ""):
    """Called by LimitlessSportsFeeder to pass edge data to the strategy."""
    _sports_edge_data[event_id] = {
        "total_yes": total_yes,
        "edge": edge,
        "outcomes_count": outcomes_count,
        "title": title,
    }


class SportsArbitrageStrategy(BaseStrategy):
    def __init__(
        self,
        symbol: str,
        feeder_type: str = "limitless_sports",
        min_edge_pct: float = 0.03,
        position_size_usd: float = 10.0,
        max_hold_seconds: float = 300.0,
        stop_loss_pct: float = 0.10,
        cooldown_seconds: float = 30.0,
        db=None,
        worker_id: str = "worker_3",
    ):
        super().__init__(symbol)
        self.feeder_type = feeder_type
        self.min_edge_pct = min_edge_pct
        self.position_size_usd = position_size_usd
        self.max_hold_seconds = float(
            os.getenv("SPORTS_MAX_HOLD_SECONDS", str(max_hold_seconds))
        )
        self.stop_loss_pct = float(
            os.getenv("SPORTS_STOP_LOSS_PCT", str(stop_loss_pct))
        )
        self.cooldown_seconds = float(
            os.getenv("SPORTS_COOLDOWN_SECONDS", str(cooldown_seconds))
        )
        self.db = db
        self.worker_id = worker_id

        self._positions = {}
        self._arb_history = []
        self._last_signal_time = {}
        self._exit_times = {}

        self.teorical_probability = 0.50
        self.edge = 0.0
        self.total_opportunities = 0

    def on_price_update(self, event: PriceUpdateEvent) -> SignalEvent:
        super().on_price_update(event)

        self.teorical_probability = event.price

        event_id = event.symbol
        now = asyncio.get_event_loop().time()

        # --- EXIT CHECKS for existing positions ---
        if event_id in self._positions:
            pos = self._positions[event_id]
            entry_price = pos["entry_price"]
            elapsed = now - pos["entry_time"]

            profit_pct = (event.price - entry_price) / entry_price if entry_price > 0 else 0

            # Time stop
            if elapsed >= self.max_hold_seconds:
                return self._trigger_exit(event_id, event.price, profit_pct,
                    f"Time Stop ({elapsed:.0f}s >= {self.max_hold_seconds:.0f}s)")

            # Stop loss
            if self.stop_loss_pct > 0 and profit_pct <= -self.stop_loss_pct:
                return self._trigger_exit(event_id, event.price, profit_pct,
                    f"Stop Loss ({profit_pct:+.2%} <= -{self.stop_loss_pct:.2%})")

            # Edge disappeared (opportunity closed)
            edge_data = _sports_edge_data.get(event_id)
            if edge_data and edge_data["edge"] < 0:
                return self._trigger_exit(event_id, event.price, profit_pct,
                    f"Edge negativo ({edge_data['edge']:+.2%})")

            return None

        # --- ENTRY CHECKS ---
        # Cooldown: no re-signal same event within N seconds
        if event_id in self._last_signal_time:
            if now - self._last_signal_time[event_id] < self.cooldown_seconds:
                return None

        # Read edge data from the shared store (written by feeder)
        edge_data = _sports_edge_data.get(event_id)
        if edge_data is None:
            self.edge = 0.0
            return None

        total_yes = edge_data["total_yes"]
        self.edge = edge_data["edge"]
        outcomes_count = edge_data["outcomes_count"]

        if self.edge < self.min_edge_pct:
            return None

        # Don't re-enter if already in a position for this event
        if event_id in self._positions:
            return None

        self.total_opportunities += 1
        self._positions[event_id] = {
            "entry_time": now,
            "entry_price": event.price,
            "edge": self.edge,
            "total_yes": total_yes,
        }
        self._last_signal_time[event_id] = now

        direction = "BUY_UNDERPRICED" if self.edge > 0 else "SELL_OVERPRICED"
        reason = (
            f"Sports Arb [{direction}]: {edge_data.get('title', event_id)} | "
            f"Sum YES={total_yes:.4f} | Edge={self.edge:+.2%} | "
            f"{outcomes_count} outcomes"
        )

        if self.db:
            self.db.log("INFO", f"[Sports-Arb] {reason}", self.worker_id)

        return SignalEvent(
            symbol=event_id,
            side="BUY",
            price=event.price,
            reason=reason,
            amount=self.position_size_usd,
        )

    def _trigger_exit(self, event_id: str, price: float, profit_pct: float, reason: str) -> SignalEvent:
        """Close a sports position."""
        pos = self._positions.pop(event_id, None)
        self._exit_times[event_id] = asyncio.get_event_loop().time()

        entry_price = pos["entry_price"] if pos else price
        pnl = (price - entry_price) * self.position_size_usd if entry_price > 0 else 0.0

        full_reason = (
            f"Sports Exit: {reason} | "
            f"Profit: {profit_pct:+.2%}"
        )

        if self.db:
            self.db.log("INFO", f"[Sports-Arb] {full_reason}", self.worker_id)

        from src.security import security_guard
        security_guard.record_pnl(self.worker_id, pnl)

        return SignalEvent(
            symbol=event_id,
            side="SELL",
            price=price,
            reason=full_reason,
            amount=self.position_size_usd,
        )

    def evaluate_signal(self, event: PriceUpdateEvent) -> SignalEvent:
        return None
