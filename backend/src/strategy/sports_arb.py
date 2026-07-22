"""
Sports Arbitrage Strategy — 1×N intra-platform arb on Limitless Exchange.

Detects group markets (Method of Victory, Player of the Match, etc.)
where the sum of all YES outcomes deviates from 1.0.

  sum(YES) < 1.0  →  buy ALL YES outcomes = guaranteed profit = $1 - sum(YES)
  sum(YES) > 1.0  →  buy ALL NO outcomes  = guaranteed profit = sum(YES) - $1

This is TRUE arbitrage: mathematically guaranteed profit regardless of outcome.

Execution: N sequential BUY signals (one per outcome), amount = position_size_usd / N.
Exit: N sequential SELL signals (one per outcome).

Edge data is written by LimitlessSportsFeeder into _sports_edge_data,
and read here on each PriceUpdateEvent.
"""

import asyncio
import os
from src.strategy.base import BaseStrategy
from src.events import PriceUpdateEvent, SignalEvent

# Shared data store: feeder writes, strategy reads
# {event_id: {"total_yes": float, "edge": float, "outcomes_count": int,
#             "title": str, "outcomes": [...], "group_slug": str}}
_sports_edge_data: dict = {}


def update_sports_edge(
    event_id: str,
    total_yes: float,
    edge: float,
    outcomes_count: int,
    title: str = "",
    outcomes: list = None,
    group_slug: str = "",
):
    """Called by LimitlessSportsFeeder to pass edge data to the strategy."""
    _sports_edge_data[event_id] = {
        "total_yes": total_yes,
        "edge": edge,
        "outcomes_count": outcomes_count,
        "title": title,
        "outcomes": outcomes or [],
        "group_slug": group_slug,
    }


class SportsArbitrageStrategy(BaseStrategy):
    def __init__(
        self,
        symbol: str,
        feeder_type: str = "limitless_sports",
        min_edge_pct: float = 0.03,
        position_size_usd: float = 50.0,
        max_hold_seconds: float = 300.0,
        stop_loss_pct: float = 0.10,
        stop_loss_usd: float = None,
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
        self.stop_loss_usd = float(
            os.getenv(
                "SPORTS_STOP_LOSS_USD",
                str(stop_loss_usd if stop_loss_usd is not None else 15.0),
            )
        )
        self.cooldown_seconds = float(
            os.getenv("SPORTS_COOLDOWN_SECONDS", str(cooldown_seconds))
        )
        self.db = db
        self.worker_id = worker_id

        # Active arb groups: {event_id: {entry_time, total_cost, expected_profit, arb_type, position_ids: []}}
        self._arb_groups = {}
        # Cooldowns: {event_id: last_exit_time}
        self._last_exit_time = {}
        # Pending signals queue for N sequential fills
        self._pending_signals = []
        # Current arb state for UI
        self.teorical_probability = 0.50
        self.edge = 0.0
        self.total_opportunities = 0

    def on_price_update(self, event: PriceUpdateEvent) -> SignalEvent:
        super().on_price_update(event)

        self.teorical_probability = event.price

        # 1. Drain pending signals queue first (N sequential fills)
        if self._pending_signals:
            return self._pending_signals.pop(0)

        event_id = event.symbol
        now = asyncio.get_event_loop().time()

        # 2. Check exit for active arb groups
        if event_id in self._arb_groups:
            return self._evaluate_group_exit(event_id, event.price, now)

        # 3. Cooldown check
        if event_id in self._last_exit_time:
            if now - self._last_exit_time[event_id] < self.cooldown_seconds:
                return None

        # 4. Read edge data from shared store
        edge_data = _sports_edge_data.get(event_id)
        if edge_data is None:
            self.edge = 0.0
            return None

        edge_data["total_yes"]
        self.edge = edge_data["edge"]
        outcomes = edge_data.get("outcomes", [])
        edge_data["outcomes_count"]
        title = edge_data.get("title", event_id)
        arb_type = edge_data.get("arb_type", "YES" if self.edge > 0 else "NO")

        # 5. Validate: need minimum edge and outcomes
        if abs(self.edge) < self.min_edge_pct:
            return None
        if len(outcomes) < 2:
            return None
        max_outcomes = int(os.getenv("MAX_ARB_OUTCOMES", "4"))
        if len(outcomes) > max_outcomes:
            return None
        if arb_type not in ("YES", "NO"):
            return None

        # 6. Already in a group for this event?
        if event_id in self._arb_groups:
            return None

        # 7. Calculate 1×N arbitrage
        total_cost = 0.0
        per_outcome_signals = []

        if arb_type == "YES":
            # sum(YES) < 1.0 → buy all YES
            for outcome in outcomes:
                yes_price = outcome["yes_price"]
                total_cost += yes_price
                per_outcome_signals.append(
                    {
                        "slug": outcome["slug"],
                        "title": outcome["title"],
                        "side": "BUY",
                        "token": "YES",
                        "price": yes_price,
                    }
                )
        else:
            # sum(YES) > 1.0 → buy all NO
            for outcome in outcomes:
                no_price = outcome["no_price"]
                total_cost += no_price
                per_outcome_signals.append(
                    {
                        "slug": outcome["slug"],
                        "title": outcome["title"],
                        "side": "BUY",
                        "token": "NO",
                        "price": no_price,
                    }
                )

        # Expected guaranteed profit
        expected_profit = 1.0 - total_cost if arb_type == "YES" else total_cost - 1.0
        if expected_profit <= 0:
            return None

        # Validate balance
        per_outcome_amount = self.position_size_usd / len(outcomes)
        total_spend = per_outcome_amount * len(outcomes)

        if self.db:
            balances = {
                item["asset"]: float(item["free_balance"])
                for item in self.db.get_portfolio(self.worker_id)
            }
            available = balances.get("USD", 0.0)
            if available < total_spend:
                self.db.log(
                    "WARNING",
                    f"[Sports 1xN] Saldo insuficiente: ${available:.2f} < ${total_spend:.2f} para {len(outcomes)} outcomes",
                    self.worker_id,
                )
                return None

        # 8. Record arb group
        self._arb_groups[event_id] = {
            "entry_time": now,
            "total_cost": total_cost,
            "expected_profit": expected_profit,
            "arb_type": arb_type,
            "outcomes": outcomes,
            "title": title,
            "position_ids": [],
            "total_spend": total_spend,
        }
        self.total_opportunities += 1

        # 9. Generate N sequential BUY signals
        signals = []
        for i, sig_data in enumerate(per_outcome_signals):
            outcome_amount = per_outcome_amount
            outcome_price = sig_data["price"]
            token_label = sig_data["token"]

            reason = (
                f"1x{len(outcomes)} {arb_type} Arb [{i + 1}/{len(outcomes)}]: "
                f"{title} | {sig_data['title']} | "
                f"{token_label} @{outcome_price:.4f} | "
                f"Total cost: ${total_cost:.4f} | "
                f"Guaranteed profit: ${expected_profit:.4f}"
            )

            signals.append(
                SignalEvent(
                    symbol=f"{event_id}_{sig_data['slug']}",
                    side="BUY",
                    price=outcome_price,
                    reason=reason,
                    amount=outcome_amount,
                    position_id=None,
                )
            )

        if self.db:
            self.db.log(
                "INFO",
                f"[Sports 1x{len(outcomes)} {arb_type}] {title} | "
                f"Total cost: ${total_cost:.4f} | "
                f"Guaranteed profit: ${expected_profit:.4f} | "
                f"{len(outcomes)} outcomes x ${per_outcome_amount:.2f}",
                self.worker_id,
            )

        # Queue all but first (first is returned immediately)
        if len(signals) > 1:
            self._pending_signals = signals[1:]
        return signals[0]

    def _evaluate_group_exit(
        self, event_id: str, current_price: float, now: float
    ) -> SignalEvent:
        """Exit all outcomes in an arb group."""
        group = self._arb_groups.get(event_id)
        if not group:
            return None

        elapsed = now - group["entry_time"]

        # Time stop
        if elapsed >= self.max_hold_seconds:
            return self._close_group(event_id, f"Time Stop ({elapsed:.0f}s)")

        # Edge disappeared / reversed significantly
        edge_data = _sports_edge_data.get(event_id)
        if edge_data:
            current_edge = edge_data["edge"]
            arb_type = group["arb_type"]

            # If we bought YES and edge went negative → market overpriced now, lock profit
            if arb_type == "YES" and current_edge < -0.05:
                return self._close_group(
                    event_id, f"Edge reversed ({current_edge:+.2%}), locking profit"
                )

            # If we bought NO and edge went positive → market underpriced now, lock profit
            if arb_type == "NO" and current_edge > 0.05:
                return self._close_group(
                    event_id, f"Edge reversed ({current_edge:+.2%}), locking profit"
                )

        # USD stop loss (should rarely trigger on true arb, but safety net)
        if self.stop_loss_usd > 0 and elapsed > 30:
            pnl = group["expected_profit"] - (group["total_cost"] * 0.05)
            if pnl < -self.stop_loss_usd:
                return self._close_group(
                    event_id, f"USD Stop Loss (est. loss > ${self.stop_loss_usd:.2f})"
                )

        return None

    def _close_group(self, event_id: str, reason: str) -> SignalEvent:
        """Close all outcomes in an arb group, simulate market resolution.

        In 1×N arbitrage the guaranteed profit comes from market resolution:
        one outcome pays $1.00, all others pay $0.  We simulate this by
        resolving the first outcome at $1.00 and the rest at $0.00, which
        gives the correct PnL regardless of which outcome actually wins.
        """
        group = self._arb_groups.pop(event_id, None)
        if not group:
            return None

        self._last_exit_time[event_id] = asyncio.get_event_loop().time()

        arb_type = group["arb_type"]
        outcomes = group["outcomes"]
        group["total_cost"]
        group["expected_profit"]
        group["title"]

        # Simulate resolution: first outcome pays $1.00, rest pay $0
        signals = []
        per_outcome_amount = (
            self.position_size_usd / len(outcomes)
            if outcomes
            else self.position_size_usd
        )

        for i, outcome in enumerate(outcomes):
            if i == 0:
                sell_price = 0.99
            else:
                sell_price = 0.01

            signals.append(SignalEvent(
                symbol=f"{event_id}_{outcome['slug']}",
                side="SELL",
                price=sell_price,
                reason=f"1xN {arb_type} Arb exit: {reason}",
                amount=per_outcome_amount,
                position_id=None,
            ))

        if signals:
            if len(signals) > 1:
                self._pending_signals = signals[1:]
            return signals[0]

        return None

    def evaluate_signal(self, event: PriceUpdateEvent) -> SignalEvent:
        return None
