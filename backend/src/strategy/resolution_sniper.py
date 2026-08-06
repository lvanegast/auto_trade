"""
Resolution Sniper Strategy — Buy near-certain markets and hold until resolution.

Strategy:
  - Monitors sports markets where YES price > 0.95 (95%+ probability)
  - Buys YES contracts at 95-98¢
  - Holds until market resolves
  - Receives $1.00 per contract on resolution
  - Edge = 1.0 - buy_price (typically 2-5% per trade)

Capital requirements:
  - Works with small capital ($2-10 per event)
  - Position size = $2 per event (configurable)
  - Expected: ~3-5% return per successful resolution

Risk:
  - Near-zero if outcome is truly certain
  - Main risk: "certain" outcome doesn't happen (rare upsets)
  - No stop-loss: hold to resolution (win or lose)
"""

import os
import time as _time
from src.strategy.base import BaseStrategy
from src.events import PriceUpdateEvent, SignalEvent


# Shared data store: feeder writes, strategy reads
_sniper_data: dict = {}


def update_sniper_data(
    event_id: str,
    yes_price: float,
    title: str = "",
    slug: str = "",
    sport: str = "",
):
    """Called by ResolutionSniperFeeder to pass market data to the strategy."""
    _sniper_data[event_id] = {
        "yes_price": yes_price,
        "title": title,
        "slug": slug,
        "sport": sport,
        "updated_at": _time.time(),
    }


class ResolutionSniperStrategy(BaseStrategy):
    def __init__(
        self,
        symbol: str,
        feeder_type: str = "resolution_sniper",
        min_entry_price: float = 0.95,
        max_entry_price: float = 0.98,
        position_size_usd: float = 2.0,
        cooldown_seconds: float = 60.0,
        db=None,
        worker_id: str = "worker_7",
    ):
        super().__init__(symbol)
        self.feeder_type = feeder_type
        self.min_entry_price = float(
            os.getenv("SNIPER_MIN_ENTRY_PRICE", str(min_entry_price))
        )
        self.max_entry_price = float(
            os.getenv("SNIPER_MAX_ENTRY_PRICE", str(max_entry_price))
        )
        self.position_size_usd = float(
            os.getenv("SNIPER_POSITION_SIZE_USD", str(position_size_usd))
        )
        self.cooldown_seconds = float(
            os.getenv("SNIPER_COOLDOWN_SECONDS", str(cooldown_seconds))
        )
        self.db = db
        self.worker_id = worker_id

        # Active sniper positions: {event_id: {entry_time, buy_price, amount, title, slug}}
        self._active_positions = {}
        # Cooldowns: {event_id: last_exit_time}
        self._last_exit_time = {}
        # Pending signals queue
        self._pending_signals = []
        # Track claimed events
        self._pending_event_ids = set()
        self._last_observation_time = {}

        # Stats
        self.teorical_probability = 0.50
        self.edge = 0.0
        self.total_opportunities = 0
        self.total_positions_taken = 0

    def on_price_update(self, event: PriceUpdateEvent) -> SignalEvent | None:
        super().on_price_update(event)

        self.teorical_probability = event.price

        # 1. Drain pending signals queue first
        if self._pending_signals:
            return self._pending_signals.pop(0)

        event_id = event.symbol
        now = _time.time()

        # 2. Check if we have an active position — monitor for resolution
        if event_id in self._active_positions:
            return self._check_resolution(event_id, event.price, now)

        # 3. Skip if already claimed
        if event_id in self._pending_event_ids:
            return None

        # 4. Cooldown check
        if event_id in self._last_exit_time:
            if now - self._last_exit_time[event_id] < self.cooldown_seconds:
                return None

        # 5. Read sniper data from shared store
        sniper_data = _sniper_data.get(event_id)
        if sniper_data is None:
            return None

        yes_price = sniper_data["yes_price"]
        title = sniper_data.get("title", event_id)

        # 6. Check if price is in sniper range (0.95 - 0.98)
        if yes_price < self.min_entry_price or yes_price > self.max_entry_price:
            self.edge = 0.0
            return None

        # 7. Calculate edge
        self.edge = round(1.0 - yes_price, 4)
        if now - self._last_observation_time.get(event_id, 0) < self.cooldown_seconds:
            return None
        self._last_observation_time[event_id] = now
        self.total_opportunities += 1

        # 8. Log opportunity and record for tracking
        if self.db:
            self.db.log(
                "INFO",
                f"[Resolution Sniper] Opportunity: {title} | "
                f"YES @ {yes_price:.4f} | Edge: {self.edge:.4f} ({self.edge*100:.1f}%) | "
                f"Position: ${self.position_size_usd:.2f}",
                self.worker_id,
            )
            # Record opportunity for outcome tracking
            opp_id = self.db.record_opportunity({
                "platform_a": "limitless",
                "platform_b": "crypto",
                "event_id": event_id,
                "event_title": title,
                "gross_edge_pct": self.edge * 100,
                "net_edge_pct": self.edge * 100,
                "platform_a_yes_ask": yes_price,
                "platform_b_no_ask": 0.0,
                "platform_a_depth": 0,
                "platform_b_depth": 0,
                "liquidity_verified": True,
                "viable": self.edge >= 0.02,
                "entry_price": yes_price,
                "expected_profit": self.edge * self.position_size_usd,
            })
            # Telegram alert for sniper opportunities (only once per event)
            from src.telegram_bot import telegram_bot
            if telegram_bot.enabled and self.edge >= 0.02:
                now_ts = _time.time()
                last_alert = getattr(self, '_last_telegram_alert', {}).get(event_id, 0)
                if now_ts - last_alert > 3600:  # 1 hour cooldown
                    telegram_bot.send_opportunity(title, self.edge * 100, "Limitless", "Crypto")
                    if not hasattr(self, '_last_telegram_alert'):
                        self._last_telegram_alert = {}
                    self._last_telegram_alert[event_id] = now_ts

        if self.db:
            self.db.log(
                "INFO",
                f"[Resolution Sniper] OBSERVATION ONLY: {title} | "
                f"YES @ {yes_price:.4f} | "
                f"Hypothetical edge: {self.edge*100:.1f}% | No order generated",
                self.worker_id,
            )

        # Deliberately no SignalEvent: this strategy is structurally read-only.
        return None

    def _check_resolution(self, event_id: str, current_price: float, now: float) -> SignalEvent | None:
        """Check if position has resolved (price dropped to 0 or jumped to 1.0)."""
        position = self._active_positions.get(event_id)
        if not position:
            return None

        elapsed = now - position["entry_time"]
        buy_price = position["buy_price"]
        num_contracts = position["num_contracts"]
        title = position["title"]

        # Check for resolution signals:
        # - Price dropped significantly (outcome lost): YES price → 0
        # - Price jumped to 1.0 (outcome won): YES price → 1.0
        # - Price stable (event still live): do nothing

        # Resolution detected if price moved significantly from entry
        price_change = current_price - buy_price

        # Case 1: Outcome won (price → 1.0 or very close)
        if current_price >= 0.99:
            payout = num_contracts * 1.0
            profit = payout - position["total_spend"]
            self._close_position(event_id, "WON", profit, payout)
            return None  # No signal needed — settlement handles payout

        # Case 2: Outcome lost (price → 0 or very close)
        if current_price <= 0.01:
            loss = position["total_spend"]
            self._close_position(event_id, "LOST", -loss, 0)
            return None  # No signal needed — settlement handles loss

        # Case 3: Extended hold (24+ hours) — might be stuck
        if elapsed > 86400:  # 24 hours
            if self.db:
                self.db.log(
                    "WARNING",
                    f"[Resolution Sniper] Position held > 24h: {title} | "
                    f"Entry: {buy_price:.4f} | Current: {current_price:.4f} | "
                    f"Elapsed: {elapsed/3600:.1f}h",
                    self.worker_id,
                )

        # Still live — no action
        return None

    def _close_position(self, event_id: str, outcome: str, profit: float, payout: float):
        """Close a sniper position after resolution."""
        position = self._active_positions.pop(event_id, None)
        if not position:
            return

        self._pending_event_ids.discard(event_id)
        self._last_exit_time[event_id] = _time.time()

        title = position["title"]
        buy_price = position["buy_price"]
        num_contracts = position["num_contracts"]
        total_spend = position["total_spend"]

        # Update tracking with resolution
        if self.db:
            opp_id = getattr(self, '_tracked_opportunities', {}).get(event_id)
            if opp_id:
                self.db.update_opportunity_resolution(
                    opp_id, 
                    "won" if outcome == "WON" else "lost",
                    profit
                )

        if self.db:
            if outcome == "WON":
                self.db.log(
                    "INFO",
                    f"[Resolution Sniper] WON: {title} | "
                    f"Bought @ {buy_price:.4f} | "
                    f"{num_contracts:.2f} contracts | "
                    f"Payout: ${payout:.2f} | "
                    f"Profit: ${profit:.4f} ({profit/total_spend*100:.1f}%)",
                    self.worker_id,
                )
                # Telegram alert for win
                from src.telegram_bot import telegram_bot
                if telegram_bot.enabled:
                    telegram_bot.send_alert("profit", 
                        f"Resolution Sniper WON: {title}\n"
                        f"Bought @ {buy_price:.4f}\n"
                        f"Payout: ${payout:.2f}\n"
                        f"Profit: +${profit:.4f} (+{profit/total_spend*100:.1f}%)")
            else:
                self.db.log(
                    "INFO",
                    f"[Resolution Sniper] LOST: {title} | "
                    f"Bought @ {buy_price:.4f} | "
                    f"{num_contracts:.2f} contracts | "
                    f"Loss: ${abs(profit):.2f}",
                    self.worker_id,
                )
                # Telegram alert for loss
                from src.telegram_bot import telegram_bot
                if telegram_bot.enabled:
                    telegram_bot.send_alert("loss",
                        f"Resolution Sniper LOST: {title}\n"
                        f"Bought @ {buy_price:.4f}\n"
                        f"Loss: -${abs(profit):.2f}")

    def evaluate_signal(self, event: PriceUpdateEvent) -> SignalEvent | None:
        return None
