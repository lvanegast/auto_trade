"""
Estrategia de Arbitraje Cross-Platform para mercados de predicción.

Detecta discrepancias de precios entre Kalshi y Polymarket para el mismo
evento real y genera señales de arbitraje (comprar YES barato + cubrir NO caro).

Requiere:
    - CrossPlatformTracker singleton para compartir precios entre workers
    - market_pairs.py para mapear contratos equivalentes
"""

import asyncio
from src.strategy.base import BaseStrategy
from src.strategy.cross_platform_tracker import cross_platform_tracker
from src.strategy.market_pairs import (
    get_pair_by_kalshi_ticker,
    get_pair_by_polymarket_token,
)
from src.events import PriceUpdateEvent, SignalEvent


class CrossPlatformArbitrageStrategy(BaseStrategy):
    def __init__(
        self,
        symbol: str,
        feeder_type: str = "kalshi",
        min_edge_pct: float = 0.03,
        position_size_pct: float = 0.5,
        max_hold_seconds: float = 120.0,
        db=None,
        worker_id: str = "worker_2",
    ):
        super().__init__(symbol)
        self.feeder_type = feeder_type.lower()
        self.min_edge_pct = min_edge_pct
        self.position_size_pct = position_size_pct
        self.max_hold_seconds = max_hold_seconds
        self.db = db
        self.worker_id = worker_id
        self._position_id = None
        self._tracker = cross_platform_tracker

        # Resolver event_id a partir del símbolo
        self.event_id = self._resolve_event_id()

        # Estado de la posición
        self.last_position = None  # 'BUY', 'SELL', None
        self.entry_price = 0.0
        self.entry_time = None
        self.last_arbitrage_opportunity = None

        # Para UI
        self.teorical_probability = 0.50
        self.edge = 0.0
        self.kelly_recommendation = 0.0

    def _resolve_event_id(self) -> str | None:
        """Resuelve el event_id lógico a partir del ticker/token del feeder."""
        if self.feeder_type == "kalshi":
            pair = get_pair_by_kalshi_ticker(self.symbol)
            return pair["event_id"] if pair else None
        elif self.feeder_type == "polymarket":
            pair = get_pair_by_polymarket_token(self.symbol)
            return pair["event_id"] if pair else None
        return None

    def on_price_update(self, event: PriceUpdateEvent) -> SignalEvent:
        """Procesa cada tick y evalúa arbitraje cross-platform."""
        super().on_price_update(event)

        if self.event_id is None:
            return None

        current_price = event.price
        self.teorical_probability = current_price

        # 1. Actualizar nuestro precio en el tracker
        self._tracker.update_price(
            event_id=self.event_id,
            platform=self.feeder_type,
            price=current_price,
            bid=event.bid,
            ask=event.ask,
        )

        # 2. Si tenemos posición abierta, evaluar salida
        if self.last_position is not None:
            return self._evaluate_exit(current_price)

        # 3. Evaluar oportunidad de arbitraje
        opp = self._tracker.calculate_arbitrage(
            self.event_id, min_edge_pct=self.min_edge_pct
        )

        if opp is None:
            self.edge = 0.0
            self.kelly_recommendation = 0.0
            self.last_arbitrage_opportunity = None
            return None

        # Guardar última oportunidad para UI
        self.last_arbitrage_opportunity = opp
        self.edge = opp["edge_pct"]

        # Verificar que esta oportunidad involucra nuestro platform como el barato
        if opp["buy_platform"] != self.feeder_type:
            # La otra plataforma tiene el precio barato; el otro worker ejecutará
            self.kelly_recommendation = 0.0
            return None

        # 4. Kelly sizing: f = edge / (odds - 1) simplificado para binarios
        # Para binarios: f = edge / cost (aproximación conservadora)
        cost = opp["total_cost"]
        if cost > 0 and cost < 1.0:
            self.kelly_recommendation = self.position_size_pct * (opp["edge_pct"] / cost)
        else:
            self.kelly_recommendation = 0.0

        # 5. Generar señal de entrada
        if self.kelly_recommendation > 0.01:
            self.last_position = "BUY"
            self.entry_price = current_price
            self.entry_time = asyncio.get_event_loop().time()

            # Persistir posición en DB
            if self.db:
                self._position_id = self.db.save_position(
                    self.worker_id,
                    self.symbol,
                    "BUY",
                    current_price,
                    opp["polymarket_yes"] if self.feeder_type == "kalshi" else opp["kalshi_yes"],
                )

            profit_str = f"{opp['edge_pct']:.2%}"
            reason = (
                f"Arbitraje Cross-Platform detectado: "
                f"YES @{self.feeder_type.upper()}={current_price:.4f} vs "
                f"otro platform. Edge: {profit_str} "
                f"(Costo total: {cost:.4f}, Ganancia garantizada: {opp['guaranteed_profit']:.4f})"
            )

            if self.db:
                self.db.log(
                    "INFO",
                    f"[Cross-Arb] Oportunidad: {self.event_id} | "
                    f"Kalshi YES={opp['kalshi_yes']:.4f} | "
                    f"Polymarket YES={opp['polymarket_yes']:.4f} | "
                    f"Edge: {profit_str}",
                    self.worker_id,
                )

            return SignalEvent(
                symbol=self.symbol,
                side="BUY",
                price=current_price,
                reason=reason,
                amount=self.kelly_recommendation,
                position_id=self._position_id,
            )

        return None

    def _evaluate_exit(self, current_price: float) -> SignalEvent:
        """Evalúa si cerrar la posición de arbitraje."""
        now = asyncio.get_event_loop().time()
        elapsed = now - self.entry_time

        # Calcular retorno actual
        profit_pct = (current_price - self.entry_price) / self.entry_price

        # Salida 1: Tiempo máximo de mantenimiento
        if elapsed >= self.max_hold_seconds:
            side = "SELL"
            reason = (
                f"Time Stop cross-platform ({elapsed:.1f}s). "
                f"Retorno: {profit_pct:+.2%}"
            )
            return self._trigger_exit(side, current_price, reason)

        # Salida 2: El arbitraje se cerró (el otro platform se movió hacia nosotros)
        # Si la oportunidad desapareció, cerramos para liberar capital
        if self.last_arbitrage_opportunity is not None:
            opp = self._tracker.calculate_arbitrage(
                self.event_id, min_edge_pct=self.min_edge_pct
            )
            if opp is None:
                side = "SELL"
                reason = (
                    f"Oportunidad de arbitraje cerrada. "
                    f"Retorno: {profit_pct:+.2%}"
                )
                return self._trigger_exit(side, current_price, reason)

        return None

    def _trigger_exit(self, side: str, price: float, reason: str) -> SignalEvent:
        """Cierra la posición y registra en DB."""
        closed_position_id = self._position_id

        if self._position_id and self.db:
            self.db.close_position(
                self._position_id, price, reason, worker_id=self.worker_id
            )

        self.last_position = None
        self.entry_price = 0.0
        self.entry_time = None
        self._position_id = None

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
