"""
Pruebas automáticas unitarias para el módulo ExecutionFrictionGuard.
"""

import pytest
from src.engine.friction_guard import ExecutionFrictionGuard, friction_guard


def test_friction_calculation_limitless_sports():
    """Valida que los costos de gas de Limitless no sobrepasen el beneficio en posiciones pequeñas."""
    fg = ExecutionFrictionGuard()
    
    # Posición de $10 USD con 3% de Edge bruto
    # Fricción: $0.02 USD de gas = 0.20% del total. Fricción total = 0.40%
    # Profit Neto = 3.0% - 0.40% = 2.60% -> DEBE APROBAR
    is_prof, net_edge, reason = fg.validate_arbitrage_profitability("limitless_sports", gross_edge_pct=0.03, position_size_usd=10.0)
    assert is_prof is True
    assert net_edge > 0.01
    assert "APROBADO" in reason


def test_friction_rejection_low_edge_high_fee():
    """Valida que una posición con baja ganancia y altas comisiones (Kalshi / IBKR) sea rechazada."""
    fg = ExecutionFrictionGuard()
    
    # Edge de solo 0.80% en Kalshi (fee 0.70% + slippage 0.15% = 0.85% de fricción)
    # Net Profit = 0.80% - 0.85% = -0.05% -> DEBE RECHAZAR
    is_prof, net_edge, reason = fg.validate_arbitrage_profitability("kalshi", gross_edge_pct=0.008, position_size_usd=50.0)
    assert is_prof is False
    assert net_edge < 0.01
    assert "RECHAZADO POR FRICCIÓN" in reason
