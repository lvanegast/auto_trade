"""
Prueba unitaria para la integración del Feeder de Hyperliquid.
"""

import pytest
import asyncio
from src.feeders.hyperliquid_feeder import HyperliquidFeeder, HyperliquidTracker


@pytest.mark.asyncio
async def test_hyperliquid_feeder_initialization():
    """Valida la instanciación y registro de precios en HyperliquidTracker."""
    queue = asyncio.Queue()
    feeder = HyperliquidFeeder(symbol="BTC", event_queue=queue)
    
    assert feeder.symbol == "BTC"
    
    # Simular actualización de precio
    HyperliquidTracker.update_price("BTC", 67500.0, 67490.0, 67510.0)
    data = HyperliquidTracker.get_price("BTC")
    
    assert data is not None
    assert data["price"] == 67500.0
    assert data["bid"] == 67490.0
    assert data["ask"] == 67510.0
