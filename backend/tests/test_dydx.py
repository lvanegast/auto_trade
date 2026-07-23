"""
Prueba unitaria para el conector de dYdX v4.
"""

import pytest
import asyncio
from src.feeders.dydx_feeder import DydxFeeder, DydxTracker


@pytest.mark.asyncio
async def test_dydx_feeder_initialization():
    """Valida la instanciación y registro de precios en DydxTracker."""
    queue = asyncio.Queue()
    feeder = DydxFeeder(symbol="BTC", event_queue=queue)
    
    assert feeder.symbol == "BTC"
    
    DydxTracker.update_price("BTC", 67600.0, 67590.0, 67610.0)
    data = DydxTracker.get_price("BTC")
    
    assert data is not None
    assert data["price"] == 67600.0
    assert data["bid"] == 67590.0
    assert data["ask"] == 67610.0
