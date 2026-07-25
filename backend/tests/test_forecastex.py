"""
Prueba unitaria para el conector de ForecastEx (IBKR).
"""

import pytest
import asyncio
from src.feeders.forecastex_feeder import ForecastExFeeder, ForecastExTracker


@pytest.mark.asyncio
async def test_forecastex_feeder_initialization():
    """Valida la instanciación y registro de precios en ForecastExTracker."""
    queue = asyncio.Queue()
    feeder = ForecastExFeeder(symbol="FED_RATE", event_queue=queue)
    
    assert feeder.symbol == "FED_RATE"
    
    ForecastExTracker.update_price("FED_RATE", 0.52, 0.515, 0.525)
    data = ForecastExTracker.get_price("FED_RATE")
    
    assert data is not None
    assert data["price"] == 0.52
    assert data["bid"] == 0.515
    assert data["ask"] == 0.525
