from src.engine.risk_manager import RiskManager


def test_stop_loss_evaluation():
    rm = RiskManager()

    # Precios para una posición BUY: entrada @ 100, actual @ 90 -> caída de -10%
    triggered, reason = rm.evaluate_stop_loss_take_profit(
        current_price=90.0,
        entry_price=100.0,
        side="BUY",
        stop_loss_pct=0.05,  # 5% SL
    )
    assert triggered is True
    assert "STOP_LOSS" in reason


def test_take_profit_evaluation():
    rm = RiskManager()

    # Precios para una posición BUY: entrada @ 100, actual @ 110 -> subida de +10%
    triggered, reason = rm.evaluate_stop_loss_take_profit(
        current_price=110.0,
        entry_price=100.0,
        side="BUY",
        take_profit_pct=0.08,  # 8% TP
    )
    assert triggered is True
    assert "TAKE_PROFIT" in reason


def test_no_trigger_normal_movement():
    rm = RiskManager()

    # Movimiento normal dentro de límites: entrada @ 100, actual @ 102
    triggered, reason = rm.evaluate_stop_loss_take_profit(
        current_price=102.0,
        entry_price=100.0,
        side="BUY",
        stop_loss_pct=0.05,
        take_profit_pct=0.08,
    )
    assert triggered is False
    assert reason == ""
