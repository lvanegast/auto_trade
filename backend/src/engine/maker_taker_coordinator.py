"""
MakerTakerCoordinator — Coordinador de ejecución asíncrona para Maker Leg 1 + Taker Leg 2 Hedge.

Resuelve el problema de "Leg Risk" y el bloqueo síncrono de órdenes Maker en Limitless:
1. Pata 1 (Maker): Se coloca al bid con post_only=True y se registra como orden RESTING
   sin bloquear el bucle de eventos ni aplicar un timeout artificial de 30 segundos.
2. Monitoreo Activo (Guardianes en tiempo real):
   - Adverse Selection Guard: Si Binance detecta un salto brusco (>12 bps en 500ms),
     la orden se cancela antes de que un taker nos cruce con toxic flow.
   - Spread Viability Guard: Si el ask de la Pata 2 sube tal que Pata1_bid + Pata2_ask > 0.98,
     la orden Pata 1 se cancela para no arriesgar un descalce en la cobertura.
   - Expiration Guard: Cancela la orden si faltan menos de N segundos para el cierre del mercado.
3. Pata 2 (Taker Hedge Inmediato):
   - En el instante en que Pata 1 confirma fill (WS Settlement MINED o REST sync),
     dispara INMEDIATAMENTE una orden FOK Taker al ask de la Pata 2.
   - Cero riesgo de posición huérfana direccional.
"""

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from src.events import SignalEvent


@dataclass
class RestingMakerOrder:
    order_id: str
    worker_id: str
    market_slug: str
    token_id: str
    side: str
    price: float
    spend_amount: float
    shares: float
    leg_name: str  # "YES" o "NO"
    hedge_token_id: str
    hedge_leg_name: str  # "NO" o "YES"
    hedge_max_price: float
    max_total_cost: float = 0.98
    target_asset: Optional[str] = None  # "BTC", "ETH", etc.
    created_at: float = field(default_factory=time.time)
    expires_at: Optional[float] = None  # Timestamp de vencimiento del mercado
    status: str = "RESTING"  # RESTING, FILLED, CANCELLED, HEDGED, HEDGE_FAILED
    cancel_reason: Optional[str] = None
    hedge_order_id: Optional[str] = None
    hedge_price: Optional[float] = None
    filled_price: Optional[float] = None
    filled_qty: Optional[float] = None


@dataclass
class MakerPair:
    pair_id: str
    market_slug: str
    worker_id: str
    yes_order_id: str
    no_order_id: str
    target_total_cost: float
    created_at: float = field(default_factory=time.time)
    first_fill_time: Optional[float] = None
    status: str = "OPEN"  # OPEN, BOTH_FILLED, HEDGED_FOK, CANCELLED


class MakerTakerCoordinator:
    """Gestiona el ciclo de vida de órdenes Maker descansando en el libro y su cobertura Taker inmediata."""

    def __init__(self, db=None):
        self.db = db
        self._resting_orders: Dict[str, RestingMakerOrder] = {}
        self._pairs: Dict[str, MakerPair] = {}

    def register_pair(
        self,
        market_slug: str,
        yes_order_id: str,
        no_order_id: str,
        target_total_cost: float,
        worker_id: str,
    ) -> MakerPair:
        """Registra un par de 2 patas Maker en el mismo mercado."""
        pair = MakerPair(
            pair_id=f"pair_{market_slug}",
            market_slug=market_slug,
            worker_id=worker_id,
            yes_order_id=yes_order_id,
            no_order_id=no_order_id,
            target_total_cost=target_total_cost,
        )
        self._pairs[market_slug] = pair
        return pair

    def get_pair(self, market_slug: str) -> Optional[MakerPair]:
        return self._pairs.get(market_slug)

    def evaluate_pair(
        self,
        market_slug: str,
        current_yes_ask: float,
        current_no_ask: float,
        max_unhedged_wait_s: float = 15.0,
        now: Optional[float] = None,
    ) -> Tuple[str, Optional[SignalEvent]]:
        """
        Evalúa el estado del par de 2 patas Maker.
        Si una pata se llenó y la otra no lo ha hecho tras `max_unhedged_wait_s`,
        activa el Guardrail FOK para cerrar inmediatamente la cobertura a mercado.
        """
        pair = self.get_pair(market_slug)
        if not pair or pair.status in ("BOTH_FILLED", "HEDGED_FOK", "CANCELLED"):
            return pair.status if pair else "NOT_FOUND", None

        yes_order = self.get_resting_order(pair.yes_order_id)
        no_order = self.get_resting_order(pair.no_order_id)

        if not yes_order or not no_order:
            return "MISSING_ORDERS", None

        yes_filled = yes_order.status == "FILLED"
        no_filled = no_order.status == "FILLED"

        if yes_filled and no_filled:
            pair.status = "BOTH_FILLED"
            return "BOTH_FILLED", None

        if not yes_filled and not no_filled:
            return "BOTH_RESTING", None

        # Asimetría detectada: una pata se llenó y la otra sigue resting
        now_t = now if now is not None else time.time()
        if pair.first_fill_time is None:
            pair.first_fill_time = now_t

        elapsed = now_t - pair.first_fill_time

        # Si expiró el tiempo de espera seguro (ej 15s), activar Guardrail FOK
        if elapsed >= max_unhedged_wait_s:
            if yes_filled and not no_filled:
                # YES se llenó -> cerrar NO con FOK a mercado
                fok_sig = self.build_hedge_signal(yes_order, current_no_ask)
                pair.status = "HEDGED_FOK"
                return "TRIGGER_FOK_NO", fok_sig
            elif no_filled and not yes_filled:
                # NO se llenó -> cerrar YES con FOK a mercado
                fok_sig = self.build_hedge_signal(no_order, current_yes_ask)
                pair.status = "HEDGED_FOK"
                return "TRIGGER_FOK_YES", fok_sig

        return "ONE_FILLED_AWAITING", None

    def register_order(self, order: RestingMakerOrder) -> None:
        """Registra una orden Maker que ha entrado al libro (post_only) en estado RESTING."""
        self._resting_orders[order.order_id] = order
        if self.db:
            try:
                self.db.log(
                    "INFO",
                    f"[MakerCoordinator] Orden {order.order_id[:8]} registrada como RESTING en "
                    f"{order.market_slug} ({order.leg_name} @ {order.price:.4f}, size=${order.spend_amount:.2f})",
                    order.worker_id,
                )
            except Exception:
                pass

    def get_resting_order(self, order_id: str) -> Optional[RestingMakerOrder]:
        return self._resting_orders.get(order_id)

    def get_active_orders(self, worker_id: Optional[str] = None) -> List[RestingMakerOrder]:
        orders = [o for o in self._resting_orders.values() if o.status == "RESTING"]
        if worker_id:
            orders = [o for o in orders if o.worker_id == worker_id]
        return orders

    def check_adverse_selection(self, order_id: str) -> Tuple[bool, str]:
        """
        Verifica si el spot en Binance tuvo un salto brusco (>12 bps en 500ms).
        Si hubo salto, retorna (True, razon_cancelacion).
        """
        order = self.get_resting_order(order_id)
        if not order or order.status != "RESTING":
            return False, "orden_no_activa"

        if not order.target_asset:
            return False, "sin_activo_referencia"

        try:
            from src.strategy.lead_lag_arbitrage import BinanceTracker
            is_jump, jump_bps = BinanceTracker.detect_jump(
                order.target_asset, window_seconds=0.5, threshold_bps=12.0
            )
            if is_jump:
                reason = f"adverse_selection_jump_{order.target_asset}_{jump_bps:.1f}bps"
                return True, reason
        except Exception as e:
            return False, f"error_oracle: {e}"

        return False, "ok"

    def check_spread_viability(self, order_id: str, current_hedge_ask: float) -> Tuple[bool, str]:
        """
        Verifica si la suma (Maker_bid + Hedge_ask) sigue siendo <= max_total_cost (ej 0.98).
        Si el ask de la pata de cobertura subió demasiado, retorna (False, razon).
        """
        order = self.get_resting_order(order_id)
        if not order or order.status != "RESTING":
            return False, "orden_no_activa"

        if current_hedge_ask <= 0:
            return False, "hedge_ask_invalido"

        total_cost = round(order.price + current_hedge_ask, 4)
        if total_cost > order.max_total_cost:
            reason = f"spread_unfavorable_total_{total_cost:.4f}_gt_{order.max_total_cost:.4f}"
            return False, reason

        return True, f"viable_cost_{total_cost:.4f}"

    def check_expiration(self, order_id: str, now: Optional[float] = None, min_buffer_seconds: float = 60.0) -> Tuple[bool, str]:
        """
        Verifica si faltan menos de min_buffer_seconds para que expire el mercado.
        Si está muy cerca de expirar, retorna (True, razon_cancelacion).
        """
        order = self.get_resting_order(order_id)
        if not order or order.status != "RESTING":
            return False, "orden_no_activa"

        if not order.expires_at:
            return False, "sin_timestamp_expiracion"

        now_t = now if now is not None else time.time()
        time_left = order.expires_at - now_t
        if time_left <= min_buffer_seconds:
            reason = f"near_expiration_{time_left:.1f}s_remaining"
            return True, reason

        return False, f"time_left_{time_left:.1f}s"

    def mark_filled(
        self,
        order_id: str,
        filled_price: Optional[float] = None,
        filled_qty: Optional[float] = None,
    ) -> Optional[RestingMakerOrder]:
        """Marca la orden Pata 1 como FILLED al recibir confirmación on-chain."""
        order = self.get_resting_order(order_id)
        if not order:
            return None

        order.status = "FILLED"
        if filled_price is not None:
            order.filled_price = filled_price
        else:
            order.filled_price = order.price

        if filled_qty is not None:
            order.filled_qty = filled_qty
        else:
            order.filled_qty = order.shares

        if self.db:
            try:
                self.db.log(
                    "INFO",
                    f"🎯 [MakerCoordinator] Pata 1 FILLED: {order.order_id[:8]} en {order.market_slug} "
                    f"({order.leg_name} qty={order.filled_qty:.4f} @ {order.filled_price:.4f})",
                    order.worker_id,
                )
            except Exception:
                pass

        return order

    def mark_cancelled(self, order_id: str, reason: str) -> Optional[RestingMakerOrder]:
        """Marca la orden Pata 1 como CANCELLED."""
        order = self.get_resting_order(order_id)
        if not order:
            return None

        order.status = "CANCELLED"
        order.cancel_reason = reason
        if self.db:
            try:
                self.db.log(
                    "INFO",
                    f"[MakerCoordinator] Orden {order.order_id[:8]} cancelada en {order.market_slug}. Razón: {reason}",
                    order.worker_id,
                )
            except Exception:
                pass
        return order

    def mark_hedged(self, order_id: str, hedge_order_id: str, hedge_price: float) -> Optional[RestingMakerOrder]:
        """Registra la exitosa cobertura Taker de la Pata 2."""
        order = self.get_resting_order(order_id)
        if not order:
            return None

        order.status = "HEDGED"
        order.hedge_order_id = hedge_order_id
        order.hedge_price = hedge_price

        total_cost = (order.filled_price or order.price) + hedge_price
        edge = 1.0 - total_cost

        if self.db:
            try:
                self.db.log(
                    "INFO",
                    f"💎 [MakerCoordinator] PAR 1xN COMPLETAMENTE CUBIERTO: {order.market_slug} | "
                    f"L1 {order.leg_name} @ {order.filled_price:.4f} + L2 {order.hedge_leg_name} @ {hedge_price:.4f} = "
                    f"Costo ${total_cost:.4f} | Margen Neto: {edge:.2%}",
                    order.worker_id,
                )
            except Exception:
                pass
        return order

    def mark_hedge_failed(self, order_id: str, reason: str) -> Optional[RestingMakerOrder]:
        """Registra fallo en la Pata 2 para activar el procedimiento de emergencia."""
        order = self.get_resting_order(order_id)
        if not order:
            return None

        order.status = "HEDGE_FAILED"
        order.cancel_reason = f"hedge_failed: {reason}"
        if self.db:
            try:
                self.db.log(
                    "CRITICAL",
                    f"🚨 [MakerCoordinator] FALLO EN HEDGE para {order.market_slug} (Pata 1 {order.order_id[:8]} ya llena). Razón: {reason}",
                    order.worker_id,
                )
            except Exception:
                pass
        return order

    def build_hedge_signal(self, order: RestingMakerOrder, current_hedge_ask: float) -> SignalEvent:
        """
        Construye la señal de disparo inmediato para la Pata 2 (Taker FOK a mercado).
        El monto a comprar se calcula para igualar el payout o los contratos de la Pata 1.
        """
        contracts = order.filled_qty or order.shares
        hedge_symbol = f"limitless_crypto_{order.market_slug}_{order.hedge_leg_name}"
        spend_usd = round(contracts * current_hedge_ask, 4)

        return SignalEvent(
            symbol=hedge_symbol,
            side="BUY",
            price=current_hedge_ask,
            reason=f"Taker Hedge L2: BUY {order.hedge_leg_name} FOK @{current_hedge_ask:.4f} to cover L1 {order.order_id[:8]}",
            position_size_usd=spend_usd,
            position_id=None,
            order_type="FOK",
        )

    def on_ws_order_event(self, data: dict) -> Optional[Tuple[str, str]]:
        """
        Procesa eventos del WebSocket `subscribe_order_events`.
        Retorna (order_id, action) donde action puede ser "FILLED", "CANCELLED", o None.
        """
        if not isinstance(data, dict):
            return None

        order_id = data.get("orderId")
        if not order_id or order_id not in self._resting_orders:
            return None

        event_type = data.get("type")
        source = data.get("source")

        if source == "SETTLEMENT":
            if event_type == "MINED":
                self.mark_filled(order_id)
                return order_id, "FILLED"
            elif event_type == "FAILED":
                self.mark_cancelled(order_id, "settlement_failed")
                return order_id, "CANCELLED"
        elif event_type == "CANCELLATION":
            self.mark_cancelled(order_id, "external_cancellation")
            return order_id, "CANCELLED"

        return None


# Singleton global para coordinar entre feeder, estrategia y supervisor
maker_taker_coordinator = MakerTakerCoordinator()
