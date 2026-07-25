"""
Pruebas automáticas unitarias para estrategias de Arbitraje:
1. Sports Arbitrage (1×N intra-platform en Limitless Exchange)
2. Cross-Platform Arbitrage (Kalshi vs Polymarket)
3. Binary Arbitrage (Opciones binarias de predicción)
"""

import pytest
from src.events import PriceUpdateEvent, SignalEvent
from src.strategy.sports_arb import SportsArbitrageStrategy, update_sports_edge, _sports_edge_data
from src.strategy.cross_platform_arb import CrossPlatformArbitrageStrategy
from src.strategy.binary_arb_strategy import OracleMomentumStrategy
from src.strategy.cross_platform_tracker import cross_platform_tracker


def test_sports_arbitrage_1xn_buy_yes():
    """Prueba que el arbitraje 1xN detecte cuando la suma YES < 1.0 y emita señales de COMPRA."""
    event_id = "test_event_champions_league"
    update_sports_edge(
        event_id=event_id,
        total_yes=0.94,  # Suma 94% -> Edge de +6.0% garantizado
        edge=0.06,
        outcomes_count=3,
        title="Real Madrid vs Bayern Munich",
        outcomes=[
            {"slug": "real-madrid", "title": "Real Madrid Win", "yes_price": 0.45},
            {"slug": "draw", "title": "Draw", "yes_price": 0.23},
            {"slug": "bayern", "title": "Bayern Munich Win", "yes_price": 0.26},
        ],
        group_slug=event_id
    )

    strat = SportsArbitrageStrategy(
        symbol=event_id,
        feeder_type="limitless_sports",
        min_edge_pct=0.02,
        position_size_usd=100.0,
        cooldown_seconds=0
    )

    event = PriceUpdateEvent(symbol=event_id, price=0.45, bid=0.45, ask=0.45)
    signal = strat.on_price_update(event)

    assert signal is not None
    assert signal.side.upper() == "BUY"
    assert event_id in signal.symbol
    assert "YES Arb" in signal.reason
    assert strat.edge == 0.06


def test_sports_arbitrage_no_trigger_low_edge():
    """Prueba que no emita señal si el Edge está por debajo del umbral mínimo configurado."""
    event_id = "test_event_low_edge"
    update_sports_edge(
        event_id=event_id,
        total_yes=0.995,  # Edge de solo +0.5%
        edge=0.005,
        outcomes_count=2,
        title="Lakers vs Celtics",
        outcomes=[
            {"slug": "lakers", "title": "Lakers Win", "yes_price": 0.50},
            {"slug": "celtics", "title": "Celtics Win", "yes_price": 0.495},
        ],
        group_slug=event_id
    )

    strat = SportsArbitrageStrategy(
        symbol=event_id,
        feeder_type="limitless_sports",
        min_edge_pct=0.03,  # Requiere al menos 3%
        position_size_usd=50.0
    )

    event = PriceUpdateEvent(symbol=event_id, price=0.50, bid=0.50, ask=0.50)
    signal = strat.on_price_update(event)

    assert signal is None


def test_cross_platform_tracker_and_strategy():
    """Prueba el rastreo de precios cruzados entre Kalshi y Polymarket."""
    event_id = "FED_RATE_CUT_2026"
    
    # Registrar precio en Kalshi (YES a $0.40) y Limitless/Polymarket (YES a $0.50)
    cross_platform_tracker.update_price(event_id, "kalshi", price=0.40, bid=0.39, ask=0.40)
    cross_platform_tracker.update_price(event_id, "limitless", price=0.50, bid=0.50, ask=0.51)

    both = cross_platform_tracker.get_both_prices(event_id)
    assert both["kalshi"]["price"] == 0.40
    assert both["limitless"]["price"] == 0.50

    strat = CrossPlatformArbitrageStrategy(
        symbol=event_id,
        feeder_type="kalshi",
        min_edge_pct=0.03,
        position_size_usd=50.0,
        cooldown_seconds=0
    )
    strat.event_id = event_id  # Asignar manualmente para test aislado

    event = PriceUpdateEvent(symbol=event_id, price=0.40, bid=0.39, ask=0.40)
    signal = strat.on_price_update(event)

    assert signal is not None
    assert signal.side.upper() == "BUY"
    assert "Cross-Platform Arb" in signal.reason


def test_oracle_momentum_strategy():
    """Prueba que la estrategia de Opciones Binarias responda correctamente a la actualización de precios."""
    strat = OracleMomentumStrategy(
        symbol="BTC/USD-BINARY",
        position_size_usd=25.0
    )

    event = PriceUpdateEvent(symbol="BTC/USD-BINARY", price=0.55, bid=0.54, ask=0.55)
    strat.on_price_update(event)
    assert len(strat.prices_df) >= 1
