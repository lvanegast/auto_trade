"""
Cross-Platform Arbitrage Strategy — dual mode.

Mode 1 (Cross-Platform): When both Kalshi and Limitless have the same event,
buy YES on one platform + buy NO on the other. Both legs executed as separate signals.
Guaranteed profit = $1 - (yes_ask + no_ask).

Mode 2 (1×N Intra-Platform): When only Limitless is available, detect group
markets where sum(YES) != 1.0 and buy ALL outcomes.

Mode is auto-detected: if CrossPlatformTracker has both platforms → cross-platform.
If only one platform → 1×N.

KEY CHANGE vs. old version:
  - Generates TWO signals per arbitrage (leg1 + leg2), not one
  - Uses ask prices (executable), not midpoint
  - Validates depth before sending signal
  - Friction validated across BOTH platforms
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
from src.strategy.sports_arb import _globally_claimed_events
from src.utils.bounded_dict import BoundedTimeDict


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
        max_exposure_per_event_pct: float = 0.10,
        max_exposure_per_platform_pct: float = 0.20,
        db=None,
        worker_id: str = "worker_2",
        observation_only: bool = False,
    ):
        super().__init__(symbol)
        self.feeder_type = feeder_type.lower()
        self.min_edge_pct = min_edge_pct
        self.position_size_pct = position_size_pct
        self.observation_only = observation_only
        self.position_size_usd = float(
            os.getenv(
                "CROSS_ARB_POSITION_SIZE_USD",
                str(position_size_usd if position_size_usd is not None else 50.0),
            )
        )
        self.max_hold_seconds = float(
            os.getenv("CROSS_ARB_MAX_HOLD_SECONDS", str(max_hold_seconds))
        )
        self.stop_loss_pct = float(
            os.getenv("CROSS_ARB_STOP_LOSS_PCT", str(stop_loss_pct))
        )
        self.stop_loss_usd = float(
            os.getenv(
                "CROSS_ARB_STOP_LOSS_USD",
                str(stop_loss_usd if stop_loss_usd is not None else 15.0),
            )
        )
        self.take_profit_pct = float(
            os.getenv("CROSS_ARB_TAKE_PROFIT_PCT", str(take_profit_pct))
        )
        self.cooldown_seconds = float(
            os.getenv("CROSS_ARB_COOLDOWN_SECONDS", str(cooldown_seconds))
        )
        self.max_exposure_per_event_pct = float(
            os.getenv(
                "CROSS_ARB_MAX_EXPOSURE_EVENT_PCT",
                str(max_exposure_per_event_pct),
            )
        )
        self.max_exposure_per_platform_pct = float(
            os.getenv(
                "CROSS_ARB_MAX_EXPOSURE_PLATFORM_PCT",
                str(max_exposure_per_platform_pct),
            )
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
        self._last_exit_time = BoundedTimeDict(max_size=200, ttl_seconds=3600)

        # Exposure tracking — auto-expire stale entries after 1h
        self._open_exposure_by_event = BoundedTimeDict(max_size=200, ttl_seconds=3600)
        self._open_exposure_by_platform = BoundedTimeDict(max_size=50, ttl_seconds=3600)

        self.teorical_probability = 0.50
        self.edge = 0.0
        self.kelly_recommendation = 0.0
        self.mode = "cross_platform"

    def _resolve_event_id(self) -> str | None:
        if self.feeder_type == "kalshi":
            pair = get_pair_by_kalshi_ticker(self.symbol)
            return pair["event_id"] if pair else None
        elif self.feeder_type == "limitless":
            pair = get_pair_by_limitless_slug(self.symbol)
            return pair["event_id"] if pair else None
        return None

    def _get_total_capital(self) -> float:
        if self.db:
            try:
                portfolio = self.db.get_portfolio(self.worker_id)
                return sum(float(item.get("free_balance", 0)) for item in portfolio)
            except Exception:
                pass
        return 10000.0

    def _get_platform_exposure(self, platform: str) -> float:
        return self._open_exposure_by_platform.get(platform, 0.0)

    def _get_event_exposure(self, event_id: str) -> float:
        return self._open_exposure_by_event.get(event_id, 0.0)

    def _can_open_position(self, event_id: str, platform: str, size_usd: float) -> tuple[bool, str]:
        total_capital = self._get_total_capital()
        if total_capital <= 0:
            return False, "Capital total es 0"

        event_limit = total_capital * self.max_exposure_per_event_pct
        current_event_exposure = self._get_event_exposure(event_id)
        if current_event_exposure + size_usd > event_limit:
            remaining = event_limit - current_event_exposure
            return False, (
                f"Límite evento {event_id}: "
                f"${current_event_exposure:.2f} / ${event_limit:.2f} | "
                f"Disponible: ${remaining:.2f}"
            )

        platform_limit = total_capital * self.max_exposure_per_platform_pct
        current_platform_exposure = self._get_platform_exposure(platform)
        if current_platform_exposure + size_usd > platform_limit:
            remaining = platform_limit - current_platform_exposure
            return False, (
                f"Límite plataforma {platform}: "
                f"${current_platform_exposure:.2f} / ${platform_limit:.2f} | "
                f"Disponible: ${remaining:.2f}"
            )

        return True, "OK"

    def _record_exposure(self, event_id: str, platform: str, size_usd: float):
        self._open_exposure_by_event[event_id] = (
            self._get_event_exposure(event_id) + size_usd
        )
        self._open_exposure_by_platform[platform] = (
            self._get_platform_exposure(platform) + size_usd
        )

    def _release_exposure(self, event_id: str, platform: str, size_usd: float):
        self._open_exposure_by_event[event_id] = max(
            0.0, self._get_event_exposure(event_id) - size_usd
        )
        self._open_exposure_by_platform[platform] = max(
            0.0, self._get_platform_exposure(platform) - size_usd
        )

    def on_price_update(self, event: PriceUpdateEvent) -> SignalEvent:
        super().on_price_update(event)

        if self._pending_signals:
            return self._pending_signals.pop(0)

        current_price = event.price
        self.teorical_probability = current_price

        event_key = self.event_id or event.symbol
        if event_key in _globally_claimed_events:
            return None

        real_bid = getattr(event, "bid", 0.0)
        real_ask = getattr(event, "ask", 0.0)
        if real_ask > 0 and real_bid > 0:
            no_ask = 1.0 - real_bid
            total_intra_cost = real_ask + no_ask
            if total_intra_cost < 0.97:
                now = asyncio.get_event_loop().time()
                if now - self.last_exit_time < self.cooldown_seconds:
                    return None
                if self.last_position is not None:
                    return None
                intra_edge = 1.0 - total_intra_cost
                if self.db:
                    self.db.log(
                        "INFO",
                        f"[Intra-Arb] Oportunidad: YES_ask={real_ask:.4f} + NO_ask={no_ask:.4f} = {total_intra_cost:.4f} | Edge: {intra_edge:.2%}",
                        self.worker_id,
                    )
                if self.observation_only:
                    num_sets_preview = self.position_size_usd / max(total_intra_cost, 0.01)
                    if self.db and hasattr(self.db, "record_opportunity"):
                        try:
                            self.db.record_opportunity({
                                "platform_a": self.feeder_type,
                                "platform_b": self.feeder_type,
                                "event_id": self.event_id or self.symbol,
                                "event_title": self.symbol,
                                "gross_edge_pct": intra_edge * 100,
                                "net_edge_pct": intra_edge * 100,
                                "platform_a_yes_ask": real_ask,
                                "platform_b_no_ask": no_ask,
                                "liquidity_verified": True,
                                "viable": intra_edge >= 0.02,
                                "category": "sports",
                                "direction": "BUY_ALL_NO_1XN",
                                "outcomes_count": 2,
                                "entry_price": total_intra_cost,
                                "expected_profit": intra_edge * self.position_size_usd,
                            })
                        except Exception:
                            pass
                    if intra_edge >= 0.02:
                        from src.telegram_bot import telegram_bot
                        legs_detail = (
                            f"<b>Patas (2):</b>\n"
                            f"  • YES @ ${real_ask:.4f} → ${real_ask * num_sets_preview:.2f}\n"
                            f"  • NO @ ${no_ask:.4f} → ${no_ask * num_sets_preview:.2f}\n"
                            f"<b>Total estimado:</b> ${total_intra_cost * num_sets_preview:.2f}"
                        )
                        telegram_bot.send_opportunity(
                            self.symbol, intra_edge * 100, self.feeder_type, self.feeder_type,
                            event_id=self.event_id or self.symbol, category="sports",
                            worker_id=self.worker_id, legs_detail=legs_detail,
                        )
                    return None
                return SignalEvent(
                    symbol=self.symbol,
                    side="BUY",
                    price=real_ask,
                    reason=f"Intra-Arb: YES_ask={real_ask:.4f} NO_ask={no_ask:.4f} edge={intra_edge:.2%}",
                    amount=None,
                    position_id=getattr(self, "_position_id", None),
                    position_size_usd=self.position_size_usd,
                )

        # Scan ALL pairs in the tracker for cross-platform opportunities
        # (not just self.event_id which only covers one market)
        opportunities = self._tracker.scan_all_pairs(min_edge_pct=self.min_edge_pct)
        for opp in opportunities:
            if opp.get("event_id") in _globally_claimed_events:
                continue

            from src.engine.friction_guard import friction_guard
            is_profitable, net_edge, _, friction_details = friction_guard.validate_arbitrage_profitability(
                leg1_feeder=opp["buy_platform"],
                leg2_feeder=opp["hedge_platform"],
                gross_edge_pct=opp["edge_pct"],
                position_size_usd=self.position_size_usd,
            )
            if not is_profitable:
                continue

            if self.db:
                self.db.log(
                    "INFO",
                    f"[Cross-Platform ARB] {opp['event_id']} | "
                    f"Edge: {opp['edge_pct']:.2%} Net: {net_edge:.2%} | "
                    f"Buy: {opp['buy_platform']} {opp['buy_side']} @{opp['buy_ask']:.4f} | "
                    f"Hedge: {opp['hedge_platform']} {opp['hedge_side']} @{opp['hedge_ask']:.4f}",
                    self.worker_id,
                )

            # If observation_only, just log and continue scanning
            if self.observation_only:
                if self.db and hasattr(self.db, "record_opportunity"):
                    try:
                        self.db.record_opportunity({
                            "platform_a": opp["buy_platform"],
                            "platform_b": opp["hedge_platform"],
                            "event_id": opp["event_id"],
                            "event_title": opp.get("event_title", opp["event_id"]),
                            "gross_edge_pct": opp["edge_pct"] * 100,
                            "net_edge_pct": net_edge * 100,
                            "platform_a_yes_ask": opp["buy_ask"],
                            "platform_b_no_ask": opp["hedge_ask"],
                            "platform_a_depth": opp.get("buy_depth", 0),
                            "platform_b_depth": opp.get("hedge_depth", 0),
                            "liquidity_verified": True,
                            "viable": net_edge >= 0.02,
                            "category": "sports",
                            "direction": "BUY_ALL_NO_1XN",
                            "outcomes_count": 2,
                            "entry_price": opp["buy_ask"] + opp["hedge_ask"],
                            "expected_profit": net_edge * self.position_size_usd,
                        })
                    except Exception:
                        pass
                if net_edge >= 0.02:
                    from src.telegram_bot import telegram_bot
                    num_sets_preview = self.position_size_usd / max(opp["buy_ask"] + opp["hedge_ask"], 0.01)
                    legs_detail = (
                        f"<b>Patas (2):</b>\n"
                        f"  • {opp['buy_platform']} {opp['buy_side']} @ ${opp['buy_ask']:.4f} "
                        f"→ ${opp['buy_ask'] * num_sets_preview:.2f}\n"
                        f"  • {opp['hedge_platform']} {opp['hedge_side']} @ ${opp['hedge_ask']:.4f} "
                        f"→ ${opp['hedge_ask'] * num_sets_preview:.2f}\n"
                        f"<b>Total estimado:</b> ${(opp['buy_ask'] + opp['hedge_ask']) * num_sets_preview:.2f}"
                    )
                    telegram_bot.send_opportunity(
                        opp["event_id"],
                        net_edge * 100,
                        opp["buy_platform"],
                        opp["hedge_platform"],
                        event_id=opp["event_id"],
                        category="sports",
                        worker_id=self.worker_id,
                        legs_detail=legs_detail,
                    )
                continue

            # Execute: buy on one platform, hedge on the other
            self.last_arbitrage_opportunity = opp
            self.edge = opp["edge_pct"]
            event_id = opp["event_id"]

            buy_ask = opp["buy_ask"]
            hedge_ask = opp["hedge_ask"]
            position_size = min(self.position_size_usd, opp.get("buy_depth", self.position_size_usd))

            can_open, limit_msg = self._can_open_position(event_id, opp["buy_platform"], position_size)
            if not can_open:
                if self.db:
                    self.db.log("WARNING", f"[Cross-Arb] {limit_msg}", self.worker_id)
                continue

            buy_qty = position_size / buy_ask if buy_ask > 0 else 0
            hedge_qty = position_size / hedge_ask if hedge_ask > 0 else 0
            if buy_qty <= 0 or hedge_qty <= 0:
                continue

            self._record_exposure(event_id, opp["buy_platform"], position_size)
            self.last_position = "BUY"
            self.entry_price = buy_ask
            self.entry_time = asyncio.get_event_loop().time()

            leg1_signal = SignalEvent(
                symbol=opp.get("buy_market", self.symbol),
                side="BUY",
                price=buy_ask,
                reason=f"Cross-Platform Arb Leg 1: {opp['buy_side']} @{opp['buy_platform']} edge={opp['edge_pct']:.2%}",
                amount=buy_qty,
                position_id=None,
                position_size_usd=position_size,
            )
            leg2_signal = SignalEvent(
                symbol=opp.get("hedge_market", self.symbol),
                side="BUY",
                price=hedge_ask,
                reason=f"Cross-Platform Arb Leg 2: {opp['hedge_side']} @{opp['hedge_platform']} edge={opp['edge_pct']:.2%}",
                amount=hedge_qty,
                position_id=None,
                position_size_usd=position_size,
            )
            self._pending_signals = [leg2_signal]
            return leg1_signal

        # Also check single-event cross-platform if event_id is set
        if self.event_id:
            both = self._tracker.get_both_books(self.event_id)
            has_kalshi = both.get("kalshi") is not None
            has_limitless = both.get("limitless") is not None

            if has_kalshi and has_limitless:
                self.mode = "cross_platform"
                return self._handle_cross_platform(event, current_price)

        self.mode = "1xN"
        return self._handle_1xN(event, current_price)

    def _handle_cross_platform(
        self, event: PriceUpdateEvent, current_price: float
    ) -> SignalEvent | None:
        # Update tracker with our price
        self._tracker.update_price(
            event_id=self.event_id,
            platform=self.feeder_type,
            price=current_price,
            bid=event.bid,
            ask=event.ask,
        )

        if self.last_position is not None:
            return self._evaluate_exit(current_price)

        now = asyncio.get_event_loop().time()
        if now - self.last_exit_time < self.cooldown_seconds:
            return None

        opp = self._tracker.calculate_arbitrage(
            self.event_id, min_edge_pct=self.min_edge_pct
        )

        if opp is None:
            self.edge = 0.0
            self.kelly_recommendation = 0.0
            self.last_arbitrage_opportunity = None
            return None

        from src.engine.friction_guard import friction_guard

        is_profitable, net_edge, _, friction_details = friction_guard.validate_arbitrage_profitability(
            leg1_feeder=opp["buy_platform"],
            leg2_feeder=opp["hedge_platform"],
            gross_edge_pct=opp["edge_pct"],
            position_size_usd=self.position_size_usd,
        )
        if not is_profitable:
            return None

        self.last_arbitrage_opportunity = opp
        self.edge = opp["edge_pct"]

        if opp["buy_platform"] != self.feeder_type:
            self.kelly_recommendation = 0.0
            return None

        buy_ask = opp["buy_ask"]
        hedge_ask = opp["hedge_ask"]

        buy_depth = opp["buy_depth"]
        hedge_depth = opp["hedge_depth"]

        max_by_depth = min(buy_depth, hedge_depth) if buy_depth > 0 and hedge_depth > 0 else self.position_size_usd
        position_size = min(self.position_size_usd, max_by_depth)
        if position_size <= 0:
            return None

        can_open, limit_msg = self._can_open_position(self.event_id, self.feeder_type, position_size)
        if not can_open:
            if self.db:
                self.db.log("WARNING", f"[Cross-Arb] {limit_msg}", self.worker_id)
            return None

        buy_qty = position_size / buy_ask if buy_ask > 0 else 0
        hedge_qty = position_size / hedge_ask if hedge_ask > 0 else 0

        if buy_qty <= 0 or hedge_qty <= 0:
            return None

        self._record_exposure(self.event_id, self.feeder_type, position_size)

        self.last_position = "BUY"
        self.entry_price = current_price
        self.entry_time = asyncio.get_event_loop().time()

        leg1_fee = friction_details["leg1_fee_per_asset"]
        leg2_fee = friction_details["leg2_fee_per_asset"]

        buy_reason = (
            f"Arb Pata 1: BUY {opp['buy_side']} @{opp['buy_platform'].upper()} "
            f"ask={buy_ask:.4f} qty={buy_qty:.2f} | "
            f"Edge: {opp['edge_pct']:.2%} Net: {net_edge:.2%} | "
            f"Leg1 Fee: ${leg1_fee:.2f} Leg2 Fee: ${leg2_fee:.2f}"
        )

        hedge_reason = (
            f"Arb Pata 2: BUY {opp['hedge_side']} @{opp['hedge_platform'].upper()} "
            f"ask={hedge_ask:.4f} qty={hedge_qty:.2f} | "
            f"Edge: {opp['edge_pct']:.2%} Net: {net_edge:.2%} | "
            f"Leg1 Fee: ${leg1_fee:.2f} Leg2 Fee: ${leg2_fee:.2f}"
        )

        if self.db:
            self.db.log("INFO", f"[Cross-Arb] {buy_reason}", self.worker_id)
            self.db.log("INFO", f"[Cross-Arb] {hedge_reason}", self.worker_id)
            self._position_id = self.db.save_position(
                self.worker_id,
                self.symbol,
                "BUY",
                buy_ask,
                hedge_ask,
            )

        leg1_signal = SignalEvent(
            symbol=self.symbol,
            side="BUY",
            price=buy_ask,
            reason=buy_reason,
            amount=buy_qty,
            position_id=self._position_id,
        )

        hedge_symbol = self._resolve_hedge_symbol(opp["hedge_platform"])
        leg2_signal = SignalEvent(
            symbol=hedge_symbol,
            side="BUY",
            price=hedge_ask,
            reason=hedge_reason,
            amount=hedge_qty,
            position_id=self._position_id,
        )

        self._pending_signals = [leg2_signal]
        return leg1_signal

    def _resolve_hedge_symbol(self, hedge_platform: str) -> str:
        if self.event_id and self.feeder_type == "kalshi":
            pair = None
            for p in __import__("src.strategy.market_pairs", fromlist=["MARKET_PAIRS"]).MARKET_PAIRS:
                if p["event_id"] == self.event_id:
                    pair = p
                    break
            if pair:
                if hedge_platform == "limitless":
                    return pair.get("limitless_slug", self.symbol)
                elif hedge_platform == "kalshi":
                    return pair.get("kalshi_ticker", self.symbol)
        return self.symbol

    def _handle_1xN(self, event: PriceUpdateEvent, current_price: float) -> SignalEvent:
        event_id = event.symbol

        if event_id in self._arb_groups:
            return self._evaluate_group_exit(event_id, current_price)

        now = asyncio.get_event_loop().time()
        if event_id in self._last_exit_time:
            if now - self._last_exit_time.get(event_id, 0) < self.cooldown_seconds:
                return None

        from src.feeders.limitless_feeder import get_macro_edge_data

        macro_data = get_macro_edge_data()
        edge_data = macro_data.get(event_id)
        if edge_data is None:
            return None

        edge = edge_data["edge"]
        outcomes = edge_data.get("outcomes", [])
        title = edge_data.get("title", event_id)

        if abs(edge) < self.min_edge_pct or len(outcomes) < 2:
            return None

        max_outcomes = int(os.getenv("MAX_ARB_OUTCOMES", "10"))
        if len(outcomes) > max_outcomes:
            return None

        if event_id in self._arb_groups:
            return None

        arb_type = "YES" if edge > 0 else "NO"
        total_cost = 0.0
        per_outcome_signals = []

        if arb_type == "YES":
            for outcome in outcomes:
                yes_price = outcome["yes_price"]
                total_cost += yes_price
                per_outcome_signals.append({
                    "slug": outcome["slug"],
                    "title": outcome["title"],
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
                    "token": "NO",
                    "price": no_price,
                })

        expected_profit = 1.0 - total_cost if arb_type == "YES" else total_cost - 1.0
        if expected_profit <= 0:
            return None

        per_outcome_amount = self.position_size_usd / len(outcomes)

        if self.db:
            balances = {
                item["asset"]: float(item["free_balance"])
                for item in self.db.get_portfolio(self.worker_id)
            }
            available = balances.get("USD", 0.0)
            if available < per_outcome_amount * len(outcomes):
                return None

        self._arb_groups[event_id] = {
            "entry_time": now,
            "total_cost": total_cost,
            "expected_profit": expected_profit,
            "arb_type": arb_type,
            "outcomes": outcomes,
            "title": title,
            "position_ids": [],
        }

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
                f"1x{len(outcomes)} {arb_type} Arb [{i + 1}/{len(outcomes)}]: "
                f"{title} | {sig_data['title']} | "
                f"{sig_data['token']} @{sig_data['price']:.4f} | "
                f"Total: ${total_cost:.4f} | Profit: ${expected_profit:.4f}"
            )

            signals.append(
                SignalEvent(
                    symbol=f"{event_id}_{sig_data['slug']}",
                    side="BUY",
                    price=sig_data["price"],
                    reason=reason,
                    amount=per_outcome_amount,
                    position_id=position_id,
                )
            )

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
        now = asyncio.get_event_loop().time()
        elapsed = now - self.entry_time

        profit_pct = (current_price - self.entry_price) / self.entry_price
        self._peak_profit = max(self._peak_profit, profit_pct)

        if not self._breakeven_activated and profit_pct >= self.take_profit_pct * 0.3:
            self._breakeven_activated = True

        if self.take_profit_pct > 0 and profit_pct >= self.take_profit_pct:
            return self._trigger_exit(
                "SELL",
                current_price,
                f"Take Profit ({profit_pct:+.2%}). Hold: {elapsed:.1f}s",
            )

        if self._breakeven_activated:
            drawdown = self._peak_profit - profit_pct
            if drawdown >= 0.005:
                return self._trigger_exit(
                    "SELL",
                    current_price,
                    f"Trailing Stop: {self._peak_profit:+.2%} -> {profit_pct:+.2%}. Hold: {elapsed:.1f}s",
                )

        if self.stop_loss_usd > 0 and profit_pct < 0:
            loss_usd = abs(profit_pct) * self.position_size_pct * self.entry_price
            if loss_usd >= self.stop_loss_usd:
                return self._trigger_exit(
                    "SELL",
                    current_price,
                    f"Stop Loss USD (${loss_usd:.2f}). Hold: {elapsed:.1f}s",
                )

        if self.stop_loss_pct > 0 and profit_pct <= -self.stop_loss_pct:
            return self._trigger_exit(
                "SELL",
                current_price,
                f"Stop Loss ({profit_pct:+.2%}). Hold: {elapsed:.1f}s",
            )

        if elapsed >= self.max_hold_seconds:
            return self._trigger_exit(
                "SELL",
                current_price,
                f"Time Stop ({elapsed:.1f}s). PnL: {profit_pct:+.2%}",
            )

        if self.last_arbitrage_opportunity:
            opp = self._tracker.calculate_arbitrage(
                self.event_id, min_edge_pct=self.min_edge_pct
            )
            if opp is None:
                return self._trigger_exit(
                    "SELL", current_price, f"Arb closed. PnL: {profit_pct:+.2%}"
                )

        return None

    def _evaluate_group_exit(self, event_id: str, current_price: float) -> SignalEvent:
        group = self._arb_groups.get(event_id)
        if not group:
            return None

        now = asyncio.get_event_loop().time()
        elapsed = now - group["entry_time"]

        if elapsed >= self.max_hold_seconds:
            return self._close_group(event_id, f"Time Stop ({elapsed:.0f}s)")

        return None

    def _close_group(self, event_id: str, reason: str) -> SignalEvent:
        group = self._arb_groups.pop(event_id, None)
        if not group:
            return None

        self._last_exit_time[event_id] = asyncio.get_event_loop().time()

        arb_type = group["arb_type"]
        outcomes = group["outcomes"]
        expected_profit = group["expected_profit"]
        title = group["title"]

        per_outcome_amount = self.position_size_usd / len(outcomes)
        total_exposure = per_outcome_amount * len(outcomes)
        self._release_exposure(event_id, self.feeder_type, total_exposure)

        for pos_id in group.get("position_ids", []):
            if self.db and pos_id:
                self.db.close_position(
                    pos_id, 0.0, f"1xN {arb_type} closed: {reason}", worker_id=self.worker_id,
                )

        from src.core.security import security_guard
        security_guard.record_pnl(self.worker_id, expected_profit)

        if self.db:
            self.db.log(
                "INFO",
                f"[Macro 1xN CLOSE] {title} | Profit: ${expected_profit:.4f} | {reason}",
                self.worker_id,
            )

        signals = []
        for i, outcome in enumerate(outcomes):
            sell_price = outcome["yes_price"] if arb_type == "YES" else outcome["no_price"]
            position_id = (
                group.get("position_ids", [None])[i]
                if i < len(group.get("position_ids", []))
                else None
            )
            signals.append(
                SignalEvent(
                    symbol=f"{event_id}_{outcome['slug']}",
                    side="SELL",
                    price=sell_price,
                    reason=f"1xN {arb_type} exit: {reason}",
                    amount=per_outcome_amount,
                    position_id=position_id,
                )
            )

        if signals:
            if len(signals) > 1:
                self._pending_signals = signals[1:]
            return signals[0]

        return None

    def _trigger_exit(self, side: str, price: float, reason: str) -> SignalEvent:
        closed_position_id = self._position_id
        self.last_exit_time = asyncio.get_event_loop().time()

        if self.last_position == "BUY":
            pnl = (price - self.entry_price) * self.position_size_pct
        elif self.last_position == "SELL":
            pnl = (self.entry_price - price) * self.position_size_pct
        else:
            pnl = 0.0

        if self.event_id and self.feeder_type:
            self._release_exposure(self.event_id, self.feeder_type, self.position_size_usd)

        if self._position_id and self.db:
            self.db.close_position(
                self._position_id, price, reason, worker_id=self.worker_id
            )

        try:
            from src.core.security import security_guard
            security_guard.record_pnl(self.worker_id, pnl)
        except (ImportError, ModuleNotFoundError):
            pass

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
            amount=None,
            position_id=closed_position_id,
        )

    def evaluate_signal(self, event: PriceUpdateEvent) -> SignalEvent:
        return None
