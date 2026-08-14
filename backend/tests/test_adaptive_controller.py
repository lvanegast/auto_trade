"""
Prueba unitaria para el Bucle de Control Adaptativo (AdaptiveController).
"""

import pytest
from src.engine.adaptive_controller import AdaptiveController


class MockDB:
    def __init__(self, trades_list):
        self.trades_list = trades_list

    def get_trades(self, worker_id: str, limit: int = 20):
        return self.trades_list


def test_adaptive_controller_excellent_performance_does_not_scale_up():
    """
    La regla de escalado de posición por buen rendimiento fue eliminada: en
    arbitraje puro el edge ya está garantizado matemáticamente al entrar, un
    Win Rate alto no lo valida ni invalida, y para estrategias de payoff
    asimétrico (Resolution Sniper) un WR~97% es justo lo esperado ANTES de la
    primera pérdida catastrófica. Rendimiento excelente ya no debe escalar
    la posición — solo se mantiene la protección defensiva.
    """
    # 10 trades ganadores sin pérdidas (Win rate 100%, PF inf)
    mock_trades = [{"pnl": 5.0} for _ in range(10)]
    db = MockDB(mock_trades)
    controller = AdaptiveController(db_manager=db)

    adj_edge, adj_pos, reason = controller.evaluate_and_adjust_worker("worker_3", current_min_edge=0.02, current_pos_size=50.0)

    assert adj_pos == 50.0  # Sin escalado — el tamaño de posición no cambia
    assert "Rendimiento Estable" in reason


def test_adaptive_controller_degraded_performance():
    """Valida la protección de capital cuando la retroalimentación muestra pérdidas."""
    # 2 victorias y 8 pérdidas (Win rate 20%)
    mock_trades = [{"pnl": -10.0} for _ in range(8)] + [{"pnl": 2.0} for _ in range(2)]
    db = MockDB(mock_trades)
    controller = AdaptiveController(db_manager=db)

    adj_edge, adj_pos, reason = controller.evaluate_and_adjust_worker("worker_1", current_min_edge=0.03, current_pos_size=50.0)

    assert adj_pos < 50.0  # Posición reducida un 20%
    assert adj_edge > 0.03  # Exigencia de Edge aumentada
    assert "Proteger Capital" in reason
