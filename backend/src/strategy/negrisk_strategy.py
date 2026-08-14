"""
NegRisk Multi-Outcome Arbitrage Strategy (Worker 7) — Módulo de Arbitraje Combinatorio en Mercados de 4 a 10 Opciones.

Escanea grupos multilaterales NegRisk en busca de ineficiencias donde sum(YES_outcomes) <= 0.95.
Ejecuta la compra del paquete completo de N opciones de forma simultánea, asegurando una ganancia libre de riesgo del 5.0% al 8.0%.
"""

import asyncio
import os
import time as _time
from src.strategy.base import BaseStrategy
from src.events import PriceUpdateEvent, SignalEvent


class NegRiskMultiOutcomeStrategy(BaseStrategy):
    def __init__(
        self,
        symbol: str,
        min_negrisk_edge_pct: float = 0.03,
        position_size_usd: float = 50.0,
        max_outcomes: int = 10,
        cooldown_seconds: float = 5.0,
        max_hold_seconds: float = 120.0,
        stop_loss_pct: float = 0.05,
        take_profit_pct: float = 0.08,
        db=None,
        worker_id: str = "worker_7",
    ):
        super().__init__(symbol)
        self.min_negrisk_edge_pct = min_negrisk_edge_pct
        self.position_size_usd = position_size_usd
        self.max_outcomes = max_outcomes
        self.cooldown_seconds = cooldown_seconds
        self.max_hold_seconds = float(os.getenv("NEGRISK_MAX_HOLD_SECONDS", str(max_hold_seconds)))
        self.stop_loss_pct = float(os.getenv("NEGRISK_STOP_LOSS_PCT", str(stop_loss_pct)))
        self.take_profit_pct = float(os.getenv("NEGRISK_TAKE_PROFIT_PCT", str(take_profit_pct)))
        self.db = db
        self.worker_id = worker_id

        self.edge = 0.0
        self.teorical_probability = 0.50
        self._last_exit_time = 0.0
        self._pending_signals = []
        self._arb_groups = {}

    def evaluate_signal(self, df):
        return None

    def on_price_update(self, event: PriceUpdateEvent) -> SignalEvent:
        super().on_price_update(event)

        if self._pending_signals:
            return self._pending_signals.pop(0)

        event_id = event.symbol
        now = _time.time()

        if event_id in self._arb_groups:
            return self._evaluate_exit(event_id, event.price, now)

        if (now - self._last_exit_time) < self.cooldown_seconds:
            return None

        from src.feeders.limitless_feeder import get_macro_edge_data
        macro_store = get_macro_edge_data()
        edge_data = macro_store.get(event.symbol)

        if not edge_data:
            return None

        outcomes = edge_data.get("outcomes", [])
        outcomes_count = len(outcomes)

        if outcomes_count < 4 or outcomes_count > self.max_outcomes:
            return None

        total_yes_cost = edge_data.get("total_yes", 1.0)
        negrisk_edge = 1.0 - total_yes_cost
        self.edge = negrisk_edge

        if abs(negrisk_edge) >= self.min_negrisk_edge_pct:
            from src.engine.friction_guard import friction_guard
            is_profitable, net_edge, _reason, _details = friction_guard.validate_arbitrage_profitability(
                "limitless", "limitless", abs(negrisk_edge), self.position_size_usd, num_legs=outcomes_count
            )

            if is_profitable:
                expected_profit = abs(negrisk_edge) * self.position_size_usd
                title = edge_data.get("title", event.symbol)

                self._arb_groups[event_id] = {
                    "entry_time": now,
                    "total_cost": total_yes_cost,
                    "expected_profit": expected_profit,
                    "outcomes": outcomes,
                    "title": title,
                    "entry_price": total_yes_cost,
                }

                if self.db:
                    self.db.log(
                        "INFO",
                        f"[NegRisk {outcomes_count}x] Entrada: '{title}' | "
                        f"Cost: ${total_yes_cost:.4f} | Edge: {negrisk_edge:.2%} | "
                        f"Profit: ${expected_profit:.2f}",
                        self.worker_id,
                    )

                arb_type = "YES" if negrisk_edge > 0 else "NO"
                pending_signals = []
                for out in outcomes:
                    if negrisk_edge > 0:
                        token_price = out.get("yes_price")
                    else:
                        no_price = out.get("no_price")
                        yes_price = out.get("yes_price")
                        token_price = no_price if no_price is not None else (
                            round(1.0 - yes_price, 6) if yes_price is not None else None
                        )
                    if token_price is None:
                        # Precio real no disponible para esta pata: abortar todo el
                        # grupo en vez de inventar un precio (rompería el 1x$1.00 garantizado).
                        if self.db:
                            self.db.log(
                                "WARNING",
                                f"[NegRisk] Abortando entrada '{title}': falta precio real para "
                                f"'{out.get('title')}' ({'yes_price' if negrisk_edge > 0 else 'no_price'}).",
                                self.worker_id,
                            )
                        del self._arb_groups[event_id]
                        return None
                    pending_signals.append(
                        SignalEvent(
                            symbol=out.get("slug", self.symbol),
                            side="BUY",
                            price=token_price,
                            reason=f"NegRisk {arb_type} Leg: {out.get('title')}",
                            amount=self.position_size_usd / outcomes_count,
                            position_id=None,
                        )
                    )

                self._pending_signals.extend(pending_signals)
                if self._pending_signals:
                    return self._pending_signals.pop(0)

        return None

    def _evaluate_exit(self, event_id: str, current_price: float, now: float) -> SignalEvent:
        group = self._arb_groups.get(event_id)
        if not group:
            return None

        elapsed = now - group["entry_time"]

        if elapsed >= self.max_hold_seconds:
            return self._close_group(event_id, f"Time Stop ({elapsed:.0f}s)")

        from src.feeders.limitless_feeder import get_macro_edge_data
        macro_store = get_macro_edge_data()
        edge_data = macro_store.get(event_id)
        if edge_data:
            current_total = edge_data.get("total_yes", 1.0)
            current_edge = 1.0 - current_total

            if current_edge <= -self.stop_loss_pct:
                return self._close_group(
                    event_id, f"Stop Loss (edge: {current_edge:+.2%})"
                )

            if current_edge >= self.take_profit_pct:
                return self._close_group(
                    event_id, f"Take Profit (edge: {current_edge:+.2%})"
                )

        return None

    def _close_group(self, event_id: str, reason: str) -> SignalEvent:
        group = self._arb_groups.pop(event_id, None)
        if not group:
            return None

        self._last_exit_time = _time.time()

        outcomes = group["outcomes"]
        entry_cost = group["total_cost"]
        expected_profit = group["expected_profit"]
        title = group["title"]

        signals = []
        per_outcome_amount = self.position_size_usd / len(outcomes) if outcomes else self.position_size_usd

        from src.feeders.limitless_feeder import get_macro_edge_data
        macro_store = get_macro_edge_data()
        edge_data = macro_store.get(event_id)
        live_outcomes = (edge_data or {}).get("outcomes", [])

        for outcome in outcomes:
            slug = outcome.get("slug", event_id)
            live = next((o for o in live_outcomes if o.get("slug") == slug), None)
            if live and live.get("yes_bid"):
                sell_price = float(live["yes_bid"])
            else:
                self._pending_signals.clear()
                return None

            signals.append(SignalEvent(
                symbol=slug,
                side="SELL",
                price=sell_price,
                reason=f"NegRisk exit: {reason} | {title}",
                amount=per_outcome_amount,
                position_id=None,
            ))

        if self.db:
            self.db.log(
                "INFO",
                f"[NegRisk] Cierre: {reason} | '{title}' | "
                f"Cost: ${entry_cost:.4f} | Expected Profit: ${expected_profit:.2f}",
                self.worker_id,
            )

        if signals:
            if len(signals) > 1:
                self._pending_signals = signals[1:]
            return signals[0]

        return None
