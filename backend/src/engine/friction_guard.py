"""
ExecutionFrictionGuard — calcula comisiones, costos de red (gas fees)
y deslizamiento (slippage) estimado para AMBOS legos de una operación cruzada.
Suma toda la fricção de ambos legos y verifica que el edge neto >= 2%.
"""

import os
from typing import Tuple, Dict, Any


class ExecutionFrictionGuard:
    def __init__(self):
        # Fees based on official Limitless documentation (July 2026):
        # - Maker (limit orders): 0% commission, 0 slippage
        # - Taker (market orders): 0.40%-3.00% dynamic curve based on price
        # - Gas: Paid by Limitless (off-chain matching), minimal for traders
        self.friction_table: Dict[str, Dict[str, float]] = {
            "limitless_sports": {
                "commission_pct": 0.00,  # Maker = 0%, Taker = 0.40%-3.00%
                "gas_fee_usd": 0.005,    # Minimal on-chain settlement cost
                "slippage_pct": 0.00,    # Maker = 0%, Taker varies
            },
            "limitless": {
                "commission_pct": 0.00,  # Maker = 0%, Taker = 0.40%-3.00%
                "gas_fee_usd": 0.005,    # Minimal on-chain settlement cost
                "slippage_pct": 0.00,    # Maker = 0%, Taker varies
            },
            "polymarket": {
                "commission_pct": 0.00,  # Maker = 0%, Taker ~1.80%
                "gas_fee_usd": 0.005,    # Polygon gas, minimal
                "slippage_pct": 0.003,
            },
            "kalshi": {
                "commission_pct": 0.007,  # 0.70% taker fee
                "gas_fee_usd": 0.00,     # CEX, no gas
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

        self.min_net_margin_pct = float(os.getenv("MIN_NET_MARGIN_PCT", "0.020"))

    def calculate_friction(self, feeder_type: str, position_size_usd: float, execution_role: str = "maker") -> Dict[str, float]:
        info = self.friction_table.get(feeder_type, {
            "commission_pct": 0.002,
            "gas_fee_usd": 0.0,
            "slippage_pct": 0.001,
        })

        if execution_role == "maker":
            # Maker orders have 0% commission on prediction markets (Polymarket/Limitless) and 0 slippage
            commission_pct = 0.00 if feeder_type in ("polymarket", "limitless", "limitless_sports", "kalshi") else info["commission_pct"] * 0.5
            slippage_pct = 0.00  # Limit Post-Only orders fill at or better than limit price
        else:
            commission_pct = info["commission_pct"]
            slippage_pct = info["slippage_pct"]

        commission_cost = position_size_usd * commission_pct
        gas_cost = info["gas_fee_usd"]
        slippage_cost = position_size_usd * slippage_pct
        total_friction_usd = commission_cost + gas_cost + slippage_cost
        total_friction_pct = (total_friction_usd / position_size_usd) if position_size_usd > 0 else 0.0

        return {
            "commission_cost_usd": round(commission_cost, 4),
            "gas_cost_usd": round(gas_cost, 4),
            "slippage_cost_usd": round(slippage_cost, 4),
            "total_friction_usd": round(total_friction_usd, 4),
            "total_friction_pct": round(total_friction_pct, 4),
            "execution_role": execution_role,
        }

    def calculate_total_friction(
        self, leg1_feeder: str, leg2_feeder: str, position_size_usd: float, execution_role: str = "maker"
    ) -> Dict[str, Any]:
        leg1_friction = self.calculate_friction(leg1_feeder, position_size_usd, execution_role)
        leg2_friction = self.calculate_friction(leg2_feeder, position_size_usd, execution_role)

        # For 1xN intra-platform arb (same feeder for both legs),
        # only charge gas ONCE since it's a single logical operation
        same_platform = (leg1_feeder == leg2_feeder)
        
        if same_platform:
            # Same platform: charge leg1 friction + leg2 commission/slippage (no double gas)
            total_friction_usd = (
                leg1_friction["total_friction_usd"] + 
                leg2_friction["commission_cost_usd"] + 
                leg2_friction["slippage_cost_usd"]
            )
        else:
            # Cross-platform: charge full friction for both legs
            total_friction_usd = (
                leg1_friction["total_friction_usd"] + leg2_friction["total_friction_usd"]
            )
        
        total_friction_pct = (
            total_friction_usd / position_size_usd if position_size_usd > 0 else 0.0
        )

        return {
            "leg1": leg1_friction,
            "leg2": leg2_friction,
            "total_friction_usd": round(total_friction_usd, 4),
            "total_friction_pct": round(total_friction_pct, 4),
            "leg1_fee_per_asset": leg1_friction["commission_cost_usd"],
            "leg2_fee_per_asset": leg2_friction["commission_cost_usd"],
            "leg1_gas": leg1_friction["gas_cost_usd"],
            "leg2_gas": leg2_friction["gas_cost_usd"] if not same_platform else 0.0,
            "leg1_slippage": leg1_friction["slippage_cost_usd"],
            "leg2_slippage": leg2_friction["slippage_cost_usd"],
            "same_platform": same_platform,
        }

    def validate_arbitrage_profitability(
        self,
        leg1_feeder: str,
        leg2_feeder: str,
        gross_edge_pct: float,
        position_size_usd: float = 50.0,
        execution_role: str = "maker",
    ) -> Tuple[bool, float, str, Dict[str, Any]]:
        friction_details = self.calculate_total_friction(
            leg1_feeder, leg2_feeder, position_size_usd, execution_role
        )

        net_edge_pct = gross_edge_pct - friction_details["total_friction_pct"]

        if net_edge_pct >= self.min_net_margin_pct:
            return (
                True,
                net_edge_pct,
                (
                    f"APROBADO [{execution_role.upper()}] | Edge Bruto: {gross_edge_pct:.2%} | "
                    f"Fricción Total: -{friction_details['total_friction_pct']:.2%} | "
                    f"Net: +{net_edge_pct:.2%}"
                ),
                friction_details,
            )
        else:
            return (
                False,
                net_edge_pct,
                (
                    f"RECHAZADO [{execution_role.upper()}] | Edge Bruto: {gross_edge_pct:.2%} | "
                    f"Fricción Total: -{friction_details['total_friction_pct']:.2%} | "
                    f"Net: {net_edge_pct:.2%} < {self.min_net_margin_pct:.2%}"
                ),
                friction_details,
            )


friction_guard = ExecutionFrictionGuard()
execution_friction_guard = friction_guard
