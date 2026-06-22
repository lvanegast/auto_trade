"""
auto_trade.feeders — Fuentes de datos de mercado (Feeders).

Cada feeder implementa BaseFeeder y produce PriceUpdateEvent en la cola asíncrona.

Clases disponibles:
    BaseFeeder      — Clase abstracta con interfaz start()/stop()
    MockFeeder      — Simulador de precios sinusoidales para testing offline
    OandaFeeder     — Streaming en tiempo real via OANDA v20 API (Forex)
    IGFeeder        — Streaming via IG Group Lightstreamer (epics IG)
"""

from src.feeders.base import BaseFeeder
from src.feeders.mock_feeder import MockFeeder
from src.feeders.oanda_feeder import OandaFeeder
from src.feeders.ig_feeder import IGFeeder
from src.feeders.binance_feeder import BinanceFeeder
from src.feeders.polymarket_feeder import PolymarketFeeder

__all__ = [
    "BaseFeeder",
    "MockFeeder",
    "OandaFeeder",
    "IGFeeder",
    "BinanceFeeder",
    "PolymarketFeeder",
]
