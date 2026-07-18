"""
Estrategia de Arbitraje Deportivo intra-platform para Limitless Exchange.

Detecta mercados grupales (Method of Victory, Player of the Match, etc.)
donde la suma de precios YES de todos los outcomes no equivale a 1.0.

Si la suma < 1.0 → profit comprando todos los outcomes (YES en cada uno)
Si la suma > 1.0 → profit vendiendo (necesitas positions existentes)

Requiere:
    - LimitlessSportsFeeder que envía PriceUpdateEvents
    - Wallet configurado con USDC en Base L2
"""

import asyncio
from src.strategy.base import BaseStrategy
from src.events import PriceUpdateEvent, SignalEvent


class SportsArbitrageStrategy(BaseStrategy):
    def __init__(
        self,
        symbol: str,
        feeder_type: str = "limitless_sports",
        min_edge_pct: float = 0.03,
        position_size_usd: float = 10.0,
        max_hold_seconds: float = 300.0,
        db=None,
        worker_id: str = "worker_3",
    ):
        super().__init__(symbol)
        self.feeder_type = feeder_type
        self.min_edge_pct = min_edge_pct
        self.position_size_usd = position_size_usd
        self.max_hold_seconds = max_hold_seconds
        self.db = db
        self.worker_id = worker_id

        self._positions = {}
        self._arb_history = []
        self._last_scan = {}

        self.teorical_probability = 0.50
        self.edge = 0.0
        self.total_opportunities = 0

    def on_price_update(self, event: PriceUpdateEvent) -> SignalEvent:
        super().on_price_update(event)

        self.teorical_probability = event.price

        event_id = event.symbol
        now = asyncio.get_event_loop().time()

        if event_id in self._last_scan:
            if now - self._last_scan[event_id] < 30:
                return None

        self._last_scan[event_id] = now

        from src.strategy.cross_platform_tracker import cross_platform_tracker
        opp = cross_platform_tracker.calculate_arbitrage(
            event_id, min_edge_pct=self.min_edge_pct
        )

        if opp is None:
            self.edge = 0.0
            return None

        self.edge = opp.get("edge_pct", 0)
        self.total_opportunities += 1

        if self.edge < self.min_edge_pct:
            return None

        if event_id in self._positions:
            return None

        self._positions[event_id] = {
            "entry_time": now,
            "edge": self.edge,
            "event_id": event_id,
        }

        reason = (
            f"Sports Arbitrage detectado: {event_id} | "
            f"Edge: {self.edge:+.2%} | "
            f"Costo total: {opp.get('total_cost', 0):.4f}"
        )

        if self.db:
            self.db.log(
                "INFO",
                f"[Sports-Arb] {reason}",
                self.worker_id,
            )

        return SignalEvent(
            symbol=event_id,
            side="BUY",
            price=event.price,
            reason=reason,
            amount=self.position_size_usd,
        )

    def evaluate_signal(self, event: PriceUpdateEvent) -> SignalEvent:
        return None
