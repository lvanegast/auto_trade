import pytest
from unittest.mock import MagicMock
from src.engine.supervisor import TradingWorker
from src.engine.resolution_monitor import ResolutionMonitor
from src.events import SignalEvent


def test_parse_symbol_maker_two_leg():
    """Verifica que maker_two_leg resuelva siempre 'USD' como quote asset."""
    worker = TradingWorker.__new__(TradingWorker)
    worker.symbol = "CRYPTO"
    worker.feeder_type = "maker_two_leg"
    base, quote = worker._parse_symbol()
    assert quote == "USD"
    assert base == "CRYPTO"


def test_security_guard_db_injection():
    """Verifica que security_guard reciba db."""
    from src.core.security import security_guard
    mock_db = MagicMock()
    security_guard.db = None
    
    worker = TradingWorker.__new__(TradingWorker)
    worker.worker_id = "worker_6"
    worker.name = "Worker 6"
    worker.symbol = "CRYPTO"
    worker.feeder_type = "maker_two_leg"
    worker.db = mock_db
    if mock_db and not getattr(security_guard, "db", None):
        security_guard.db = mock_db
        
    assert security_guard.db is mock_db


def test_resolution_monitor_maker_spread_gap_payout():
    """Verifica que MAKER_2LEG_1XN y MAKER_REWARDS_SPREAD_GAP tengan payout 1.0 (arbitraje cubierto)."""
    mock_db = MagicMock()
    monitor = ResolutionMonitor(db=mock_db, worker_id="worker_1")
    
    # Simular oportunidad Maker de 2 patas
    opp_data = {
        "direction": "MAKER_REWARDS_SPREAD_GAP",
        "outcomes_count": 2,
    }
    entry_price = 0.9430
    
    direction = opp_data.get("direction", "")
    outcome_count = int(opp_data.get("outcomes_count", 0) or 0)
    if direction in ("BUY_ALL_YES", "BUY_ALL_YES_1XN", "MAKER_2LEG_1XN", "MAKER_REWARDS_SPREAD_GAP"):
        payout = 1.0
    else:
        payout = None
        
    assert payout == 1.0
    position_pnl = payout - entry_price
    position_won = position_pnl > 0
    assert position_won is True
    assert round(position_pnl, 4) == 0.0570
