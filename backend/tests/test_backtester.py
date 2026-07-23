"""
Pruebas automáticas para el Motor de Backtesting.
"""

import pytest
import pandas as pd
import numpy as np
from src.engine.backtester import BacktestEngine
from src.strategy.sports_arb import SportsArbitrageStrategy, update_sports_edge


def test_backtest_engine_execution():
    """Valida la simulación de backtesting con una serie temporal de precios."""
    # Generar 50 barras históricas sintéticas
    now = pd.Timestamp.now()
    dates = [now + pd.Timedelta(minutes=i) for i in range(50)]
    prices = [0.45 + (0.01 * (i % 5)) for i in range(50)]

    df_history = pd.DataFrame({
        "timestamp": dates,
        "price": prices,
        "bid": [p - 0.005 for p in prices],
        "ask": [p + 0.005 for p in prices]
    })

    event_id = "backtest_sports_event"
    update_sports_edge(
        event_id=event_id,
        total_yes=0.92,  # Edge de +8%
        edge=0.08,
        outcomes_count=2,
        title="Backtest Event",
        outcomes=[
            {"slug": "team-a", "title": "Team A", "yes_price": 0.45},
            {"slug": "team-b", "title": "Team B", "yes_price": 0.47}
        ]
    )

    strat = SportsArbitrageStrategy(
        symbol=event_id,
        min_edge_pct=0.02,
        position_size_usd=50.0,
        cooldown_seconds=0
    )

    engine = BacktestEngine(initial_capital=1000.0, position_size_usd=50.0)
    results = engine.run_backtest(strat, df_history)

    assert "total_trades" in results
    assert "win_rate_pct" in results
    assert "profit_factor" in results
    assert "sharpe_ratio" in results
    assert results["final_capital"] >= 0
