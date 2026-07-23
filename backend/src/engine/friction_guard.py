"""
ExecutionFrictionGuard — calcula comisiones, costos de red (gas fees)
y deslizamiento (slippage) estimado para cada plataforma antes de autorizar una señal de arbitraje o trading.

Garantiza que la ganancia esperada sea NETA y superior al umbral mínimo de rentabilidad real.
"""

import os
from typing import Tuple, Dict, Any


class ExecutionFrictionGuard:
    def __init__(self):
        # Estructura de comisiones por plataforma (Maker / Taker / Fixed Fee)
        self.friction_table: Dict[str, Dict[str, float]] = {
            "limitless_sports": {
                "commission_pct": 0.00,       # 0% fee de exchange
                "gas_fee_usd": 0.02,          # Gas estimado en Base/Polygon por tx
                "slippage_pct": 0.002,        # 0.20% slippage estimado
            },
            "limitless": {
                "commission_pct": 0.00,
                "gas_fee_usd": 0.02,
                "slippage_pct": 0.002,
            },
            "polymarket": {
                "commission_pct": 0.00,
                "gas_fee_usd": 0.03,
                "slippage_pct": 0.003,        # 0.30% slippage en CLOB
            },
            "kalshi": {
                "commission_pct": 0.007,      # 0.70% tarifa por contrato
                "gas_fee_usd": 0.00,
                "slippage_pct": 0.0015,
            },
            "alpaca": {
                "commission_pct": 0.0025,     # 0.25% fee taker crypto/spot
                "gas_fee_usd": 0.00,
                "slippage_pct": 0.0005,
            },
            "binance": {
                "commission_pct": 0.0010,     # 0.10% fee estándar binance
                "gas_fee_usd": 0.00,
                "slippage_pct": 0.0002,
            },
            "hyperliquid": {
                "commission_pct": 0.00025,    # 0.025% Taker fee ultrabajo en Hyperliquid L1
                "gas_fee_usd": 0.00,          # $0 gas fee por orden
                "slippage_pct": 0.0002,
            },
            "dydx": {
                "commission_pct": 0.00020,    # 0.020% Taker fee en dYdX v4 AppChain
                "gas_fee_usd": 0.00,
                "slippage_pct": 0.0003,
            },
            "ibkr": {
                "commission_pct": 0.0005,
                "gas_fee_usd": 0.35,          # $0.35 USD mínimo por orden
                "slippage_pct": 0.0005,
            },
        }

        # Margen neto mínimo requerido después de restar toda la fricción
        self.min_net_margin_pct = float(os.getenv("MIN_NET_MARGIN_PCT", "0.01"))  # 1.0% neto mínimo

    def calculate_friction(self, feeder_type: str, position_size_usd: float) -> Dict[str, float]:
        """Calcula el costo total de fricción en dólares USD para un tamaño de posición."""
        info = self.friction_table.get(feeder_type, {
            "commission_pct": 0.002,
            "gas_fee_usd": 0.0,
            "slippage_pct": 0.001,
        })

        commission_cost = position_size_usd * info["commission_pct"]
        gas_cost = info["gas_fee_usd"]
        slippage_cost = position_size_usd * info["slippage_pct"]

        total_friction_usd = commission_cost + gas_cost + slippage_cost
        total_friction_pct = (total_friction_usd / position_size_usd) if position_size_usd > 0 else 0.0

        return {
            "commission_cost_usd": round(commission_cost, 4),
            "gas_cost_usd": round(gas_cost, 4),
            "slippage_cost_usd": round(slippage_cost, 4),
            "total_friction_usd": round(total_friction_usd, 4),
            "total_friction_pct": round(total_friction_pct, 4),
        }

    def validate_arbitrage_profitability(
        self,
        feeder_type: str,
        gross_edge_pct: float,
        position_size_usd: float = 50.0
    ) -> Tuple[bool, float, str]:
        """
        Evalúa si un arbitraje o trade es verdaderamente RENTABLE NETO.
        Retorna (is_profitable, net_edge_pct, reason).
        """
        friction = self.calculate_friction(feeder_type, position_size_usd)
        friction_pct = friction["total_friction_pct"]

        net_edge_pct = gross_edge_pct - friction_pct

        if net_edge_pct >= self.min_net_margin_pct:
            return True, net_edge_pct, (
                f"APROBADO RENTABLE | Edge Bruto: {gross_edge_pct:.2%} | "
                f"Fricción Total: -{friction_pct:.2%} | Net Profit: +{net_edge_pct:.2%}"
            )
        else:
            return False, net_edge_pct, (
                f"RECHAZADO POR FRICCIÓN | Edge Bruto: {gross_edge_pct:.2%} | "
                f"Fricción Total: -{friction_pct:.2%} | Net Profit Insuficiente: {net_edge_pct:.2%} "
                f"(Requerido >= {self.min_net_margin_pct:.2%})"
            )


friction_guard = ExecutionFrictionGuard()
