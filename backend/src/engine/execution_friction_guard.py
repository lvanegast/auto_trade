"""
ExecutionFrictionGuard — calcula comissões, custos de rede (gas fees)
e deslizamento (slippage) estimado para AMBOS legos de uma operação cruzada.
Soma toda a fricção de ambos os legos.
"""

import os
from typing import Tuple, Dict, Any


class ExecutionFrictionGuard:
    def __init__(self):
        # Estrutura de comissões por plataforma (Maker / Taker / Fixed Fee)
        self.friction_table: Dict[str, Dict[str, float]] = {
            "limitless_sports": {
                "commission_pct": 0.00,
                "gas_fee_usd": 0.02,
                "slippage_pct": 0.002,
            },
            "limitless": {
                "commission_pct": 0.00,
                "gas_fee_usd": 0.02,
                "slippage_pct": 0.002,
            },
            "polymarket": {
                "commission_pct": 0.00,
                "gas_fee_usd": 0.03,
                "slippage_pct": 0.003,
            },
            "kalshi": {
                "commission_pct": 0.007,
                "gas_fee_usd": 0.00,
                "slippage_pct": 0.0015,
            },
            "alpaca": {
                "commission_pct": 0.0025,
                "gas_fee_usd": 0.00,
                "slippage_pct": 0.0005,
            },
            "binance": {
                "commission_pct": 0.0010,
                "gas_fee_usd": 0.00,
                "slippage_pct": 0.0002,
            },
            "hyperliquid": {
                "commission_pct": 0.00025,
                "gas_fee_usd": 0.00,
                "slippage_pct": 0.0002,
            },
            "dydx": {
                "commission_pct": 0.00020,
                "gas_fee_usd": 0.00,
                "slippage_pct": 0.0003,
            },
            "ibkr": {
                "commission_pct": 0.0005,
                "gas_fee_usd": 0.35,
                "slippage_pct": 0.0005,
            },
        }

        # Margem líquida mínima requerida após subtrair TODA a fricção cruzada
        self.min_net_margin_pct = float(os.getenv("MIN_NET_MARGIN_PCT", "0.015"))  # 0.015 = 1.5%

    def calculate_friction(self, feeder_type: str, position_size_usd: float) -> Dict[str, float]:
        """Calcula o custo total de fricção em dólares USD para um tamanho de posição."""
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

    def calculate_total_friction(
        self, leg1_feeder: str, leg2_feeder: str, position_size_usd: float
    ) -> Dict[str, Any]:
        """Calcula a fricção TOTAL para AMBOS legos de uma operação cruzada.
        Soma a fricção de ambas as plataformas de trading.
        """
        leg1_friction = self.calculate_friction(leg1_feeder, position_size_usd)
        leg2_friction = self.calculate_friction(leg2_feeder, position_size_usd)

        total_friction_usd = (
            leg1_friction["total_friction_usd"] + leg2_friction["total_friction_usd"]
        )
        total_friction_pct = (
            total_friction_usd / position_size_usd
            if position_size_usd > 0
            else 0.0
        )

        return {
            "leg1": leg1_friction,
            "leg2": leg2_friction,
            "total_friction_usd": round(total_friction_usd, 4),
            "total_friction_pct": round(total_friction_pct, 4),
            "leg1_fee_per_asset": leg1_friction["commission_cost_usd"],
            "leg2_fee_per_asset": leg2_friction["commission_cost_usd"],
            "leg1_gas": leg1_friction["gas_cost_usd"],
            "leg2_gas": leg2_friction["gas_cost_usd"],
            "leg1_slippage": leg1_friction["slippage_cost_usd"],
            "leg2_slippage": leg2_friction["slippage_cost_usd"],
        }

    def validate_arbitrage_profitability(
        self,
        leg1_feeder: str,
        leg2_feeder: str,
        gross_edge_pct: float,
        position_size_usd: float = 50.0
    ) -> Tuple[bool, float, str, Dict[str, Any]]:
        """Avalia se uma operação cruzada é verdadeiramente RENTÁVEL LÍQUIDA.
        Retorna (is_profitable, net_edge_pct, reason, friction_details).
        """
        friction_details = self.calculate_total_friction(
            leg1_feeder, leg2_feeder, position_size_usd
        )

        net_edge_pct = gross_edge_pct - friction_details["total_friction_pct"]

        if net_edge_pct >= self.min_net_margin_pct:
            return (
                True,
                net_edge_pct,
                (
                    f"APROVADO RENTÁVEL | Edge Bruto: {gross_edge_pct:.2%} | "
                    f"Fricção Total Cruzada: -{friction_details['total_friction_pct']:.2%} | "
                    f"Profit Neto: +{net_edge_pct:.2%}"
                ),
                friction_details,
            )
        else:
            return (
                False,
                net_edge_pct,
                (
                    f"REJEITADO POR FRICÇÃO CRUZADA | Edge Bruto: {gross_edge_pct:.2%} | "
                    f"Fricção Total Cruzada: -{friction_details['total_friction_pct']:.2%} | "
                    f"Profit Neto Insuficiente: {net_edge_pct:.2%} "
                    f"(Requerido >= {self.min_net_margin_pct:.2%})"
                ),
                friction_details,
            )


# Singleton instance
execution_friction_guard = ExecutionFrictionGuard()
