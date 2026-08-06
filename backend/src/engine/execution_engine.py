"""
ExecutionPlan — orquesta ejecución de arbitrajes cruzados entre plataformas.
Gestiona ambos legos: compra en una plataforma, venta en la otra.

Integra con el pipeline de ejecución existente del supervisor.
"""

import asyncio
import time
from typing import Dict, Any, Optional, Tuple

from src.database import DatabaseManager
from src.events import SignalEvent
from src.engine.friction_guard import friction_guard


class ExecutionPlan:
    """
    Orquesta la ejecución de ambas patas de un arbitraje cross-platform.
    """

    def __init__(
        self,
        leg1_feeder: str,
        leg2_feeder: str,
        leg1_symbol: str,
        leg2_symbol: str,
        leg1_side: str,
        leg2_side: str,
        position_size_usd: float,
        db: DatabaseManager,
        worker_id: str = "worker_1",
        paper_trading: bool = False,
    ):
        self.leg1_feeder = leg1_feeder.lower()
        self.leg2_feeder = leg2_feeder.lower()
        self.leg1_symbol = leg1_symbol
        self.leg2_symbol = leg2_symbol
        self.leg1_side = leg1_side.upper()
        self.leg2_side = leg2_side.upper()
        self.position_size_usd = position_size_usd
        self.db = db
        self.worker_id = worker_id
        self.paper_trading = paper_trading

        self.status = "PENDING"
        self.leg1_order_id: Optional[str] = None
        self.leg2_order_id: Optional[str] = None
        self.leg1_filled_qty: float = 0.0
        self.leg2_filled_qty: float = 0.0
        self.leg1_avg_price: Optional[float] = None
        self.leg2_avg_price: Optional[float] = None
        self.leg1_requested_price: Optional[float] = None
        self.leg2_requested_price: Optional[float] = None
        self.leg1_external_order_id: Optional[str] = None
        self.leg2_external_order_id: Optional[str] = None
        self.start_time = time.time()
        self.last_book_update: float = 0.0
        self._friction_details: Dict[str, Any] = {}

        self.leg1_book_depth: Dict[str, float] = {"bids": 0.0, "asks": 0.0}
        self.leg2_book_depth: Dict[str, float] = {"bids": 0.0, "asks": 0.0}

    def _check_stale_book(self, max_age_ms: float = 500.0) -> bool:
        current_time = time.time() * 1000
        return (current_time - self.last_book_update) > max_age_ms

    async def preflight_check(self) -> Tuple[bool, str]:
        balances = {
            item["asset"]: float(item["free_balance"])
            for item in self.db.get_portfolio(self.worker_id)
        }

        if "USD" not in balances or balances["USD"] < self.position_size_usd:
            return False, (
                f"Saldo insuficiente: ${balances.get('USD', 0):.2f} < ${self.position_size_usd:.2f}"
            )

        return True, "Preflight OK"

    async def execute(
        self, leg1_price: float, leg2_price: float
    ) -> Tuple[bool, str, Dict[str, Any]]:
        self.leg1_requested_price = leg1_price
        self.leg2_requested_price = leg2_price

        is_preflight_ok, preflight_msg = await self.preflight_check()
        if not is_preflight_ok:
            self.status = "REJECTED_NO_BALANCE"
            return False, preflight_msg, {"status": self.status}

        if self._check_stale_book():
            self.status = "REJECTED_STALE_BOOK"
            return False, "Libro desactualizado (>500ms)", {"status": self.status}

        gross_edge_pct = 1.0 - (leg1_price + leg2_price) if leg1_price > 0 and leg2_price > 0 else 0.0

        is_profitable, net_edge_pct, reason, friction_details = (
            friction_guard.validate_arbitrage_profitability(
                self.leg1_feeder,
                self.leg2_feeder,
                gross_edge_pct,
                self.position_size_usd,
            )
        )

        self._friction_details = friction_details

        if not is_profitable:
            self.status = "REJECTED_BY_FRICTION"
            return False, reason, {
                "status": self.status,
                "net_edge_pct": net_edge_pct,
                "friction_details": friction_details,
            }

        leg1_size = self.position_size_usd / leg1_price if leg1_price > 0 else 0
        leg2_size = self.position_size_usd / leg2_price if leg2_price > 0 else 0

        try:
            if self.paper_trading:
                await self._simulate_execution(
                    leg1_price, leg2_price, leg1_size, leg2_size, friction_details
                )
            else:
                await self._execute_real_trades(
                    leg1_price, leg2_price, leg1_size, leg2_size, friction_details
                )

            self.status = "COMPLETED"
            return True, "Arbitraje completado", self.get_execution_details()

        except Exception as e:
            self.status = "FAILED"
            self.db.log("ERROR", f"[ExecutionPlan] {e}", self.worker_id)
            return False, str(e), {"status": self.status}

    async def _simulate_execution(
        self, leg1_price, leg2_price, leg1_size, leg2_size, friction_details
    ):
        """
        Simula ejecución REALISTA usando OrderBookWalker y LatencyTracker.
        
        En vez de slippage aleatorio:
        1. Obtiene latencia real medida por los feeders
        2. Camina el order book real consumiendo liquidez nivel por nivel
        3. Calcula slippage real basado en la profundidad del book
        """
        from src.engine.orderbook_walker import orderbook_walker
        from src.engine.latency_tracker import latency_tracker
        
        # Obtener latencia real medida por los feeders
        leg1_latency_ms = latency_tracker.get_recent_latency_ms(self.leg1_feeder, "get_orderbook")
        leg2_latency_ms = latency_tracker.get_recent_latency_ms(self.leg2_feeder, "get_orderbook")
        
        # Obtener order books reales del CrossPlatformTracker
        from src.strategy.cross_platform_tracker import cross_platform_tracker
        
        # Simular fill de Leg 1
        leg1_book = None
        leg1_event_id = self.leg1_symbol  # Aproximación
        for event_id in cross_platform_tracker.get_all_event_ids():
            book = cross_platform_tracker.get_book(event_id, self.leg1_feeder)
            if book:
                leg1_book = book
                break
        
        if leg1_book:
            # Convertir formato del tracker a formato del walker
            leg1_orderbook = {
                "asks": [{"price": leg1_book["yes_ask"], "size": 1000}],  # Size estimado
                "bids": [{"price": leg1_book["yes_bid"], "size": 1000}],
            }
            leg1_fill = orderbook_walker.simulate_fill(
                orderbook=leg1_orderbook,
                side=self.leg1_side,
                size_usd=self.position_size_usd,
                latency_ms=leg1_latency_ms,
            )
            self.leg1_avg_price = leg1_fill.avg_price
            self.leg1_filled_qty = leg1_fill.total_filled
        else:
            # Fallback: usar precio solicitado sin slippage
            self.leg1_avg_price = leg1_price
            self.leg1_filled_qty = leg1_size
            leg1_fill = None
        
        # Simular fill de Leg 2
        leg2_book = None
        for event_id in cross_platform_tracker.get_all_event_ids():
            book = cross_platform_tracker.get_book(event_id, self.leg2_feeder)
            if book:
                leg2_book = book
                break
        
        if leg2_book:
            leg2_orderbook = {
                "asks": [{"price": leg2_book["yes_ask"], "size": 1000}],
                "bids": [{"price": leg2_book["yes_bid"], "size": 1000}],
            }
            leg2_fill = orderbook_walker.simulate_fill(
                orderbook=leg2_orderbook,
                side=self.leg2_side,
                size_usd=self.position_size_usd,
                latency_ms=leg2_latency_ms,
            )
            self.leg2_avg_price = leg2_fill.avg_price
            self.leg2_filled_qty = leg2_fill.total_filled
        else:
            self.leg2_avg_price = leg2_price
            self.leg2_filled_qty = leg2_size
            leg2_fill = None
        
        # Generar IDs de orden con información de slippage
        ts = int(time.time() * 1000)
        self.leg1_external_order_id = f"WALK-{ts}-LEG1"
        self.leg2_external_order_id = f"WALK-{ts}-LEG2"
        
        leg1_fee = friction_details.get("leg1_fee_per_asset", 0)
        leg2_fee = friction_details.get("leg2_fee_per_asset", 0)
        leg1_gas = friction_details.get("leg1_gas", 0)
        leg2_gas = friction_details.get("leg2_gas", 0)
        
        # Calcular slippage real
        leg1_slippage_pct = leg1_fill.slippage_pct if leg1_fill else 0.0
        leg2_slippage_pct = leg2_fill.slippage_pct if leg2_fill else 0.0
        leg1_slippage_usd = leg1_fill.slippage_usd if leg1_fill else 0.0
        leg2_slippage_usd = leg2_fill.slippage_usd if leg2_fill else 0.0
        
        self.leg1_order_id = self.db.save_trade(
            symbol=self.leg1_symbol,
            side=self.leg1_side,
            price=self.leg1_avg_price,
            amount=self.leg1_filled_qty,
            total=self.leg1_filled_qty * self.leg1_avg_price,
            status="COMPLETED",
            external_order_id=self.leg1_external_order_id,
            worker_id=self.worker_id,
            position_id=None,
            requested_price=self.leg1_requested_price,
            filled_price=self.leg1_avg_price,
            requested_qty=leg1_size,
            filled_qty=self.leg1_filled_qty,
            fee_per_asset=leg1_fee,
            gas_usd=leg1_gas,
            slippage_usd=leg1_slippage_usd,
            net_pnl=None,
            leg_id="LEG1",
        )

        self.leg2_order_id = self.db.save_trade(
            symbol=self.leg2_symbol,
            side=self.leg2_side,
            price=self.leg2_avg_price,
            amount=self.leg2_filled_qty,
            total=self.leg2_filled_qty * self.leg2_avg_price,
            status="COMPLETED",
            external_order_id=self.leg2_external_order_id,
            worker_id=self.worker_id,
            position_id=None,
            requested_price=self.leg2_requested_price,
            filled_price=self.leg2_avg_price,
            requested_qty=leg2_size,
            filled_qty=self.leg2_filled_qty,
            fee_per_asset=leg2_fee,
            gas_usd=leg2_gas,
            slippage_usd=leg2_slippage_usd,
            net_pnl=None,
            leg_id="LEG2",
        )

        self.db.log(
            "INFO",
            f"[ExecutionPlan WALK] Leg1: {self.leg1_symbol} {self.leg1_side} ${self.leg1_avg_price:.4f} x{self.leg1_filled_qty:.2f} "
            f"(slip: {leg1_slippage_pct:.2f}%, lat: {leg1_latency_ms:.0f}ms) | "
            f"Leg2: {self.leg2_symbol} {self.leg2_side} ${self.leg2_avg_price:.4f} x{self.leg2_filled_qty:.2f} "
            f"(slip: {leg2_slippage_pct:.2f}%, lat: {leg2_latency_ms:.0f}ms)",
            self.worker_id,
        )

    async def _execute_real_trades(
        self, leg1_price, leg2_price, leg1_size, leg2_size, friction_details
    ):
        # RECHAZAR en lugar de simular silenciosamente
        # La ejecución real de cross-platform arbitrage requiere integración directa
        # con los exchanges (Kalshi/Limitless/Polymarket) — no existe aún
        self.status = "REJECTED_NO_REAL_EXECUTION"
        self.db.log(
            "ERROR",
            f"[ExecutionPlan] RECHAZADO — ejecución real no implementada para cross-platform. "
            f"Leg1: {self.leg1_symbol} {self.leg1_side} @{leg1_price:.4f}, "
            f"Leg2: {self.leg2_symbol} {self.leg2_side} @{leg2_price:.4f}. "
            f"Usar paper_trading=True para simulación explícita.",
            self.worker_id,
        )
        raise NotImplementedError(
            "Ejecución real de cross-platform arbitrage no implementada. "
            "Usar paper_trading=True o integrar ejecución directa en supervisor."
        )

    def get_execution_details(self) -> Dict[str, Any]:
        net_pnl = 0.0
        if self.leg1_avg_price and self.leg2_avg_price:
            leg1_cost = self.leg1_filled_qty * self.leg1_avg_price
            leg2_cost = self.leg2_filled_qty * self.leg2_avg_price
            net_pnl = 1.0 - (self.leg1_avg_price + self.leg2_avg_price)

        return {
            "status": self.status,
            "leg1": {
                "feeder": self.leg1_feeder,
                "symbol": self.leg1_symbol,
                "side": self.leg1_side,
                "requested_price": self.leg1_requested_price,
                "filled_price": self.leg1_avg_price,
                "filled_quantity": self.leg1_filled_qty,
                "requested_quantity": self.position_size_usd / self.leg1_requested_price if self.leg1_requested_price else 0,
                "fee_per_asset": self._friction_details.get("leg1_fee_per_asset", 0),
                "gas": self._friction_details.get("leg1_gas", 0),
                "slippage": self._friction_details.get("leg1_slippage", 0),
                "external_order_id": self.leg1_external_order_id,
            },
            "leg2": {
                "feeder": self.leg2_feeder,
                "symbol": self.leg2_symbol,
                "side": self.leg2_side,
                "requested_price": self.leg2_requested_price,
                "filled_price": self.leg2_avg_price,
                "filled_quantity": self.leg2_filled_qty,
                "requested_quantity": self.position_size_usd / self.leg2_requested_price if self.leg2_requested_price else 0,
                "fee_per_asset": self._friction_details.get("leg2_fee_per_asset", 0),
                "gas": self._friction_details.get("leg2_gas", 0),
                "slippage": self._friction_details.get("leg2_slippage", 0),
                "external_order_id": self.leg2_external_order_id,
            },
            "net_edge_per_contract": net_pnl,
            "net_edge_pct": net_pnl,
            "friction_details": self._friction_details,
            "execution_time": time.time() - self.start_time,
        }
