"""
Sports Arbitrage Strategy — 1×N intra-platform & cross-platform arb on Limitless & Polymarket.

Detects group sports markets where the sum of all YES outcomes deviates from 1.0.
Supports outcomes filtering and cross-platform best-price selection.
"""

import asyncio
import os
import time

import time as _time
from collections import OrderedDict, deque
from datetime import datetime, timedelta

from src.strategy.base import BaseStrategy
from src.events import PriceUpdateEvent, SignalEvent
from src.utils.bounded_dict import BoundedDict, BoundedTimeDict

# Shared data store: feeder writes, strategy reads (bounded to prevent OOM)
_sports_edge_data: dict = BoundedDict(max_size=300)

# Global set of claimed event_ids to prevent concurrent workers from trading the same event
_globally_claimed_events: set = set()
MAX_EVENTS_CLAIMED = 2000


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
        outcomes_count: int = None,
        cross_platform: bool = False,
        observation_only: bool = False,
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
        self.outcomes_count = outcomes_count
        self.cross_platform = cross_platform
        self.observation_only = observation_only

        # Active arb groups: {event_id: {entry_time, total_cost, expected_profit, arb_type, position_ids: []}}
        self._arb_groups = {}
        # Cooldowns: {event_id: last_exit_time} — auto-expire after 1h
        self._last_exit_time = BoundedTimeDict(max_size=200, ttl_seconds=3600)
        # Pending signals queue for N sequential fills
        self._pending_signals = []
        # Track pending event_ids to prevent duplicate entries while fills are in progress
        self._pending_event_ids = set()
        # Telegram alert cooldowns — auto-expire after 1h
        self._last_telegram_alert = BoundedTimeDict(max_size=200, ttl_seconds=3600)
        # Current arb state for UI
        self.teorical_probability = 0.50
        self.edge = 0.0
        self.total_opportunities = 0

    def on_price_update(self, event: PriceUpdateEvent) -> SignalEvent | None:
        super().on_price_update(event)

        self.teorical_probability = event.price

        # 1. Drain pending signals queue first (N sequential fills)
        if self._pending_signals:
            return self._pending_signals.pop(0)

        event_id = event.symbol
        now = _time.time()

        # 2. Check exit for active arb groups
        if event_id in self._arb_groups:
            return self._evaluate_group_exit(event_id, event.price, now)

        # 2b. Skip if we or another worker already claimed this event (prevent cross-worker duplicate entries)
        if event_id in self._pending_event_ids or event_id in _globally_claimed_events:
            return None

        # 3. Cooldown check
        if event_id in self._last_exit_time:
            if now - self._last_exit_time.get(event_id, 0) < self.cooldown_seconds:
                return None

        # 4. Read edge data from shared store
        edge_data = _sports_edge_data.get(event_id)
        if edge_data is None:
            self.edge = 0.0
            return None

        outcomes = edge_data.get("outcomes", [])
        
        # Outcomes count filter
        if self.outcomes_count is not None and len(outcomes) != self.outcomes_count:
            return None

        title = edge_data.get("title", event_id)

        # 5. Cross-platform best price calculation: Limitless vs Polymarket/Kalshi
        # Uses REAL executable prices from orderbooks, not midpoints
        if self.cross_platform:
            from src.strategy.cross_platform_tracker import cross_platform_tracker
            from src.limitless_price_cache import get_limitless_executable_price
            total_yes = 0.0
            best_outcomes = []
            has_cross_data = False
            
            for outcome in outcomes:
                # Get REAL Limitless price from orderbook
                ll_slug = outcome.get("slug", "")
                ll_ob = get_limitless_executable_price(ll_slug)

                # Fail closed: a listing midpoint is never an executable price.
                if not ll_ob:
                    self.edge = 0.0
                    return None

                ll_yes_ask = ll_ob["yes_ask"]
                ll_yes_bid = ll_ob["yes_bid"]

                poly_book = cross_platform_tracker.get_book(event_id, "polymarket")
                kalshi_book = cross_platform_tracker.get_book(event_id, "kalshi")
                
                # Check Polymarket
                if poly_book and poly_book.get("yes_ask"):
                    poly_price = poly_book["yes_ask"]
                    has_cross_data = True
                    best_price = ll_yes_ask if ll_yes_ask <= poly_price else poly_price
                    best_platform = "limitless" if ll_yes_ask <= poly_price else "polymarket"
                # Check Kalshi
                elif kalshi_book and kalshi_book.get("yes_ask"):
                    kalshi_price = kalshi_book["yes_ask"]
                    has_cross_data = True
                    best_price = ll_yes_ask if ll_yes_ask <= kalshi_price else kalshi_price
                    best_platform = "limitless" if ll_yes_ask <= kalshi_price else "kalshi"
                else:
                    # No cross-platform data — skip (don't trade on fabricated edges)
                    continue
                
                total_yes += best_price
                best_outcomes.append({
                    "slug": outcome["slug"],
                    "title": outcome["title"],
                    "yes_price": best_price,
                    "no_price": 1.0 - best_price,
                    "platform": best_platform,
                    "limitless_bid": ll_yes_bid,
                    "limitless_ask": ll_yes_ask,
                })
            
            # If no cross-platform data available, skip
            if not has_cross_data:
                self.edge = 0.0
                return None
            
            self.edge = round(1.0 - total_yes, 4)
            outcomes = best_outcomes
            arb_type = "YES" if self.edge > 0 else "NO"
        else:
            self.edge = edge_data["edge"]
            arb_type = edge_data.get("arb_type", "YES" if self.edge > 0 else "NO")

        # 6. Validate: need minimum edge and outcomes
        if abs(self.edge) < self.min_edge_pct:
            return None

        # Sanity: edges > 15% are data errors or illiquid markets — not real arb
        if abs(self.edge) > 0.15:
            return None

        # Filtro de Rentabilidad Neta Anti-Fricción
        from src.engine.friction_guard import friction_guard
        is_profitable, net_edge, reason_guard, friction_details = friction_guard.validate_arbitrage_profitability(
            self.feeder_type, self.feeder_type, abs(self.edge), self.position_size_usd
        )
        if not is_profitable:
            if self.db:
                self.db.log("INFO", f"[Sports ARB] Friction reject: {reason_guard}", self.worker_id)
            return None
        if len(outcomes) < 2:
            return None
        max_outcomes = int(os.getenv("MAX_ARB_OUTCOMES", "10"))
        if len(outcomes) > max_outcomes:
            return None
        if arb_type not in ("YES", "NO"):
            return None

        # 7. Already in a group for this event? (memory + DB check)
        if event_id in self._arb_groups:
            return None
        if self.db:
            open_positions = self.db.get_open_positions(worker_id=None)
            for pos in open_positions:
                if pos["symbol"].endswith(event_id + "_" + outcomes[0]["slug"]):
                    return None

        # 8. Calculate 1×N arbitrage
        total_cost = 0.0
        per_outcome_signals = []

        if arb_type == "YES":
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
                        "platform": outcome.get("platform", "limitless")
                    }
                )
        else:
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
                        "platform": outcome.get("platform", "limitless")
                    }
                )

        if self.observation_only:
            from src.engine.friction_guard import friction_guard
            is_profitable, net_edge, _, _ = friction_guard.validate_arbitrage_profitability(
                "limitless", "kalshi", abs(self.edge), self.position_size_usd
            )
            if self.db:
                direction_label = "BUY_ALL_YES_1XN" if arb_type == "YES" else "BUY_ALL_NO_1XN"
                self.db.record_edge_snapshot({
                    "event_id": event_id,
                    "event_title": title,
                    "gross_edge_pct": self.edge * 100,
                    "net_edge_pct": net_edge * 100,
                    "platform_a_yes_ask": total_cost,
                    "platform_b_no_ask": 0.0,
                    "liquidity_verified": True,
                    "viable": is_profitable,
                    "category": "sports",
                    "direction": direction_label,
                    "outcomes_count": len(outcomes),
                })
                self.db.log(
                    "INFO",
                    f"[Cross-Platform Observation] {title} | "
                    f"Gross: {self.edge:.2%} | Net: {net_edge:.2%} | "
                    "No order generated",
                    self.worker_id,
                )
                # Record opportunity for outcome tracking
                opp_id = self.db.record_opportunity({
                    "platform_a": "limitless",
                    "platform_b": "kalshi",
                    "event_id": event_id,
                    "event_title": title,
                    "gross_edge_pct": self.edge * 100,
                    "net_edge_pct": net_edge * 100,
                    "platform_a_yes_ask": total_cost,
                    "platform_b_no_ask": 0.0,
                    "platform_a_depth": 0,
                    "platform_b_depth": 0,
                    "liquidity_verified": True,
                    "viable": is_profitable,
                    "category": "sports",
                    "direction": direction_label,
                    "outcomes_count": len(outcomes),
                    "entry_price": total_cost,
                    "expected_profit": net_edge * self.position_size_usd,
                    "market_slug": edge_data.get("group_slug", ""),
                })
                # Telegram alert for cross-platform opportunities (once per event per hour)
                from src.telegram_bot import telegram_bot
                if telegram_bot.enabled and net_edge >= 0.02:
                    telegram_bot.send_opportunity(title, net_edge * 100, "Limitless", "Kalshi", event_id=event_id, category="sports")
            return None

        expected_profit = (1.0 - total_cost) if arb_type == "YES" else ((len(outcomes) - 1.0) - total_cost)
        if expected_profit <= 0:
            return None

        num_sets = self.position_size_usd / max(total_cost, 0.01)
        total_spend = num_sets * total_cost

        # 9. Record arb group
        self._arb_groups[event_id] = {
            "entry_time": now,
            "total_cost": total_cost,
            "expected_profit": expected_profit,
            "arb_type": arb_type,
            "outcomes": outcomes,
            "title": title,
            "position_ids": [],
            "total_spend": total_spend,
            "num_sets": num_sets,
        }
        # If claimed events set is getting too large, clear old ones
        if len(_globally_claimed_events) > MAX_EVENTS_CLAIMED:
            _globally_claimed_events.clear()

        self._pending_event_ids.add(event_id)
        _globally_claimed_events.add(event_id)
        self.total_opportunities += 1

        # 10. Generate N sequential BUY signals — each outcome gets proportional USD
        signals = []
        for i, sig_data in enumerate(per_outcome_signals):
            outcome_price = sig_data["price"]
            outcome_amount = num_sets * outcome_price  # USD for THIS outcome
            token_label = sig_data["token"]
            platform = sig_data["platform"].upper()

            reason = (
                f"1x{len(outcomes)} {arb_type} Arb [{i + 1}/{len(outcomes)}]: "
                f"{title} | {sig_data['title']} | "
                f"{token_label} on {platform} @{outcome_price:.4f} | "
                f"Sets: {num_sets:.2f} | "
                f"Total cost: ${total_cost:.4f} | "
                f"Guaranteed profit: ${expected_profit * num_sets:.4f} | "
                f"LIMIT ORDER (maker=0% fee)"
            )

            # Suffix platform to track in DB
            symbol = f"{sig_data['platform']}_{event_id}_{sig_data['slug']}"

            signals.append(
                SignalEvent(
                    symbol=symbol,
                    side="BUY",
                    price=outcome_price,
                    reason=reason,
                    amount=None,
                    position_id=None,
                    position_size_usd=outcome_amount,
                    order_type="GTC",
                )
            )

        if self.db:
            venue = "Cross-Platform" if self.cross_platform else "Local"
            self.db.log(
                "INFO",
                f"[{venue} Sports 1x{len(outcomes)} {arb_type}] {title} | "
                f"Total cost/set: ${total_cost:.4f} | "
                f"Sets: {num_sets:.2f} | "
                f"Total spend: ${total_spend:.2f} | "
                f"Guaranteed profit: ${expected_profit * num_sets:.4f} | "
                f"{len(outcomes)} outcomes",
                self.worker_id,
            )
            # Telegram alert for 1xN arb opportunities (deduplicated via event_id)
            from src.telegram_bot import telegram_bot
            if telegram_bot.enabled and abs(self.edge) >= 0.02:
                profit_usd = expected_profit * num_sets
                telegram_bot.send_alert("opportunity",
                    f"1x{len(outcomes)} {arb_type} Arb: {title}\n"
                    f"Edge: {self.edge:.2%} | Profit: ${profit_usd:.4f}\n"
                    f"Spend: ${total_spend:.2f} | Sets: {num_sets:.2f}",
                    event_id=event_id, category="sports")

        # Queue all but first
        if len(signals) > 1:
            self._pending_signals = signals[1:]
        return signals[0]

    def _evaluate_group_exit(self, event_id: str, current_price: float, now: float) -> SignalEvent | None:
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

            if arb_type == "YES" and current_edge < -0.05:
                return self._close_group(
                    event_id, f"Edge reversed ({current_edge:+.2%}), locking profit"
                )

            if arb_type == "NO" and current_edge > 0.05:
                return self._close_group(
                    event_id, f"Edge reversed ({current_edge:+.2%}), locking profit"
                )

        if self.stop_loss_usd > 0 and elapsed > 30:
            pnl = group["expected_profit"] - (group["total_cost"] * 0.05)
            if pnl < -self.stop_loss_usd:
                return self._close_group(
                    event_id, f"USD Stop Loss (est. loss > ${self.stop_loss_usd:.2f})"
                )

        return None

    def _close_group(self, event_id: str, reason: str) -> SignalEvent | None:
        """Close all outcomes in an arb group."""
        group = self._arb_groups.pop(event_id, None)
        if not group:
            return None

        self._pending_event_ids.discard(event_id)
        _globally_claimed_events.discard(event_id)
        self._last_exit_time[event_id] = _time.time()

        arb_type = group["arb_type"]
        outcomes = group["outcomes"]
        num_sets = group.get("num_sets", 1.0)

        # Get current real-time prices for early exits
        edge_data = _sports_edge_data.get(event_id)
        current_outcomes = edge_data.get("outcomes", []) if edge_data else []
        current_prices = {o["slug"]: o for o in current_outcomes}

        # Simulate resolution: first outcome pays $1.00, rest pay $0
        signals = []
        is_early_exit = any(x in reason for x in ["Time Stop", "reversed", "Stop Loss"])

        for i, outcome in enumerate(outcomes):
            slug = outcome["slug"]
            if is_early_exit:
                # Use current market price if available, otherwise fall back to entry price
                if slug in current_prices:
                    if arb_type == "YES":
                        sell_price = current_prices[slug]["yes_price"]
                    else:
                        sell_price = current_prices[slug].get("no_price", round(1.0 - current_prices[slug]["yes_price"], 4))
                else:
                    sell_price = outcome["yes_price"] if arb_type == "YES" else outcome.get("no_price", round(1.0 - outcome["yes_price"], 4))
            else:
                # Settlement: use current market price, not fabricated resolution
                # The actual resolution is unknown until the event settles
                if slug in current_prices:
                    if arb_type == "YES":
                        sell_price = current_prices[slug]["yes_price"]
                    else:
                        sell_price = current_prices[slug].get("no_price", round(1.0 - current_prices[slug]["yes_price"], 4))
                else:
                    # No current price available — use entry price as estimate
                    sell_price = outcome["yes_price"] if arb_type == "YES" else outcome.get("no_price", round(1.0 - outcome["yes_price"], 4))

            platform = outcome.get("platform", "limitless")
            symbol = f"{platform}_{event_id}_{slug}"

            signals.append(SignalEvent(
                symbol=symbol,
                side="SELL",
                price=sell_price,
                reason=f"1xN {arb_type} Arb exit: {reason}",
                amount=num_sets,
                position_id=None,
            ))

        if signals:
            if len(signals) > 1:
                self._pending_signals = signals[1:]
            return signals[0]

        return None

    def evaluate_signal(self, event: PriceUpdateEvent) -> SignalEvent | None:
        return None
