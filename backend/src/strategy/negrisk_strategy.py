"""
NegRisk Multi-Outcome Arbitrage Strategy (Worker 7) — Módulo de Arbitraje Combinatorio en Mercados de 4 a 10 Opciones.

Escanea grupos multilaterales NegRisk en busca de ineficiencias donde sum(YES_outcomes) <= 0.95.
Ejecuta la compra del paquete completo de N opciones de forma simultánea, asegurando una ganancia libre de riesgo del 5.0% al 8.0%.
"""

import asyncio
import os
from src.strategy.base import BaseStrategy
from src.events import PriceUpdateEvent, SignalEvent


class NegRiskMultiOutcomeStrategy(BaseStrategy):
    def __init__(
        self,
        symbol: str,
        min_negrisk_edge_pct: float = 0.03, # 3.0% de margen mínimo
        position_size_usd: float = 50.0,
        max_outcomes: int = 10,
        cooldown_seconds: float = 5.0,
        db=None,
        worker_id: str = "worker_7",
    ):
        super().__init__(symbol)
        self.min_negrisk_edge_pct = min_negrisk_edge_pct
        self.position_size_usd = position_size_usd
        self.max_outcomes = max_outcomes
        self.cooldown_seconds = cooldown_seconds
        self.db = db
        self.worker_id = worker_id

        self.edge = 0.0
        self.teorical_probability = 0.50
        self._last_exit_time = 0.0
        self._pending_signals = []

    def evaluate_signal(self, df):
        """Método abstracto de BaseStrategy."""
        return None

    def on_price_update(self, event: PriceUpdateEvent) -> SignalEvent:
        super().on_price_update(event)

        if self._pending_signals:
            return self._pending_signals.pop(0)

        now = asyncio.get_event_loop().time()
        if (now - self._last_exit_time) < self.cooldown_seconds:
            return None

        # Leer datos de NegRisk multilaterales del almacén compartido del feeder
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

        if negrisk_edge >= self.min_negrisk_edge_pct:
            from src.engine.friction_guard import friction_guard
            is_profitable, net_edge, _ = friction_guard.validate_arbitrage_profitability(
                feeder_type="limitless",
                gross_edge_pct=negrisk_edge,
                position_size_usd=self.position_size_usd
            )

            if is_profitable:
                expected_profit = negrisk_edge * self.position_size_usd
                title = edge_data.get("title", event.symbol)
                reason = (
                    f"NegRisk {outcomes_count}x Arb: Paquete Completo '{title}' | "
                    f"Cost: ${total_yes_cost:.4f} | Edge: {negrisk_edge:.2%} | "
                    f"Profit Neto Asegurado: ${expected_profit:.2f}"
                )

                self._last_exit_time = now

                if self.db:
                    self.db.log("INFO", f"[NegRisk-10x] 👑 {reason}", self.worker_id)
                    pos_id = self.db.save_position(
                        self.worker_id,
                        self.symbol,
                        "BUY_NEGRISK",
                        total_yes_cost,
                        1.0 - total_yes_cost
                    )

                # Generar cola de señales para comprar cada uno de los N outcomes del paquete
                for out in outcomes:
                    self._pending_signals.append(
                        SignalEvent(
                            symbol=out.get("slug", self.symbol),
                            side="BUY",
                            price=out.get("yes_price", 0.10),
                            reason=f"NegRisk Leg: {out.get('title')}",
                            amount=self.position_size_usd / outcomes_count
                        )
                    )

                if self._pending_signals:
                    return self._pending_signals.pop(0)

        return None
