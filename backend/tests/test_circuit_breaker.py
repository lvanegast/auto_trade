"""
Prueba unitaria para el fusible financiero CircuitBreaker.
"""

import pytest
from src.engine.circuit_breaker import CircuitBreaker, circuit_breaker


def test_circuit_breaker_normal_operation():
    """Valida la operación normal del portafolio cuando la pérdida está dentro de límites."""
    cb = CircuitBreaker(max_daily_loss_pct=0.03)  # Límite de 3.0%
    cb.reset_circuit()
    
    # Capital inicial $1000, capital actual $980 (pérdida de -2.0%) -> DEBE SEGUIR OPERANDO
    is_safe, reason = cb.check_portfolio_safety(initial_capital=1000.0, current_total_equity=980.0)
    assert is_safe is True
    assert cb.is_tripped is False
    assert "Portafolio Seguro" in reason


def test_circuit_breaker_tripped_on_excessive_loss():
    """Valida el disparo instantáneo del fusible cuando la pérdida excede el 3.0%."""
    cb = CircuitBreaker(max_daily_loss_pct=0.03)
    cb.reset_circuit()

    # Capital inicial $1000, capital actual $950 (pérdida de -5.0%) -> DEBE DETENER TODO
    is_safe, reason = cb.check_portfolio_safety(initial_capital=1000.0, current_total_equity=950.0)
    assert is_safe is False
    assert cb.is_tripped is True
    assert "Pérdida diaria acumulada" in reason or "CIRCUIT BREAKER" in reason

    # Verificación de que bloquea evaluaciones subsiguientes mientras siga activado
    is_safe_2, _ = cb.check_portfolio_safety(initial_capital=1000.0, current_total_equity=990.0)
    assert is_safe_2 is False
