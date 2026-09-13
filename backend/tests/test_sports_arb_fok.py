import time
from unittest.mock import MagicMock

from src.events import PriceUpdateEvent, SignalEvent
from src.strategy.sports_arb import SportsArbitrageStrategy, update_sports_edge


def test_sports_arb_emits_fok_signals_for_3way():
    """Valida que la estrategia de deportes emite señales Taker FOK para compras simultáneas."""
    mock_db = MagicMock()
    strategy = SportsArbitrageStrategy(
        symbol="SPORTS_1XN",
        feeder_type="limitless_sports",
        min_edge_pct=0.02,
        position_size_usd=10.0,
        db=mock_db,
        worker_id="worker_3",
        observation_only=False,
    )

    # Simular partido de fútbol 3-way (Local, Empate, Visitante)
    # Ask Local: 0.42, Ask Empate: 0.26, Ask Visitante: 0.27
    # Total Ask: 0.42 + 0.26 + 0.27 = 0.95 -> Edge = 5.0%
    event_id = "match_barcelona_vs_real_madrid"
    outcomes = [
        {"slug": "barca", "title": "Barcelona", "price": 0.42, "yes_price": 0.42, "platform": "limitless"},
        {"slug": "draw", "title": "Empate", "price": 0.26, "yes_price": 0.26, "platform": "limitless"},
        {"slug": "real", "title": "Real Madrid", "price": 0.27, "yes_price": 0.27, "platform": "limitless"},
    ]
    total_yes = 0.95
    edge = 0.05

    update_sports_edge(
        event_id=event_id,
        total_yes=total_yes,
        edge=edge,
        outcomes_count=3,
        title="Barcelona vs Real Madrid",
        outcomes=outcomes,
        group_slug="barca-vs-madrid-slug",
        expiration_ts=time.time() + 7200,
        arb_type="YES",
        entry_price=total_yes,
    )

    mock_db.get_open_positions.return_value = []

    # Disparar tick para este evento (mismo symbol que event_id)
    event = PriceUpdateEvent(
        symbol=event_id,
        price=0.33,
        chart_price="Barcelona vs Real Madrid",
    )

    sig1 = strategy.on_price_update(event)

    assert sig1 is not None
    assert sig1.order_type == "FOK"
    assert sig1.side == "BUY"
    assert "TAKER FOK" in sig1.reason
    assert "barca" in sig1.symbol

    # Validar que las 2 patas restantes quedaron en _pending_signals con FOK
    assert len(strategy._pending_signals) == 2
    sig2 = strategy._pending_signals[0]
    sig3 = strategy._pending_signals[1]

    assert sig2.order_type == "FOK"
    assert sig2.side == "BUY"
    assert "draw" in sig2.symbol

    assert sig3.order_type == "FOK"
    assert sig3.side == "BUY"
    assert "real" in sig3.symbol

    # Validar que el costo total asignado de las 3 patas suma la posición
    total_spend = sig1.position_size_usd + sig2.position_size_usd + sig3.position_size_usd
    assert round(total_spend, 2) == 10.0
