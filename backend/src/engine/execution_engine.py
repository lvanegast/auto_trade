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
        import random

        slippage_leg1 = random.uniform(0, friction_details["leg1_slippage"])
        slippage_leg2 = random.uniform(0, friction_details["leg2_slippage"])

        self.leg1_avg_price = leg1_price * (1 + slippage_leg1 / leg1_price) if leg1_price > 0 else leg1_price
        self.leg2_avg_price = leg2_price * (1 + slippage_leg2 / leg2_price) if leg2_price > 0 else leg2_price

        leg1_fill_ratio = random.uniform(0.9, 1.0)
        leg2_fill_ratio = random.uniform(0.9, 1.0)

        self.leg1_filled_qty = leg1_size * leg1_fill_ratio
        self.leg2_filled_qty = leg2_size * leg2_fill_ratio

        ts = int(time.time() * 1000)
        self.leg1_external_order_id = f"SIM-{ts}-LEG1"
        self.leg2_external_order_id = f"SIM-{ts}-LEG2"

        leg1_fee = friction_details.get("leg1_fee_per_asset", 0)
        leg2_fee = friction_details.get("leg2_fee_per_asset", 0)
        leg1_gas = friction_details.get("leg1_gas", 0)
        leg2_gas = friction_details.get("leg2_gas", 0)
        leg1_slip = friction_details.get("leg1_slippage", 0)
        leg2_slip = friction_details.get("leg2_slippage", 0)

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
            slippage_usd=leg1_slip,
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
            slippage_usd=leg2_slip,
            net_pnl=None,
            leg_id="LEG2",
        )

        self.db.log(
            "INFO",
            f"[ExecutionPlan PAPER] Leg1: {self.leg1_symbol} {self.leg1_side} ${self.leg1_avg_price:.4f} x{self.leg1_filled_qty:.2f} | "
            f"Leg2: {self.leg2_symbol} {self.leg2_side} ${self.leg2_avg_price:.4f} x{self.leg2_filled_qty:.2f}",
            self.worker_id,
        )

    async def _execute_real_trades(
        self, leg1_price, leg2_price, leg1_size, leg2_size, friction_details
    ):
        self.db.log(
            "WARNING",
            "[ExecutionPlan] Ejecución real no disponible — usando simulación",
            self.worker_id,
        )
        await self._simulate_execution(
            leg1_price, leg2_price, leg1_size, leg2_size, friction_details
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
