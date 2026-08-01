"""
ForecastEx / IBKR Feeder — conector asíncrono para Interactive Brokers (ForecastEx Prediction Markets)
usando la librería ib-async.

Obtiene precios en tiempo real para eventos macroeconómicos (FED Rates, CPI, GDP) en ForecastEx (IBKR)
y los expone en la cola de eventos para arbitraje cruzado contra Polymarket / Limitless.
"""

import asyncio
import logging
import os
import time
from typing import Optional
from src.feeders.base import BaseFeeder
from src.events import PriceUpdateEvent

logger = logging.getLogger(__name__)


class ForecastExTracker:
    """Singleton tracker para almacenar precios en tiempo real de ForecastEx (IBKR)."""
    _instance = None
    latest_prices = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ForecastExTracker, cls).__new__(cls)
        return cls._instance

    @classmethod
    def update_price(cls, symbol: str, price: float, bid: float = None, ask: float = None):
        cls.latest_prices[symbol.upper()] = {
            "price": price,
            "bid": bid if bid else price,
            "ask": ask if ask else price,
            "timestamp": time.time()
        }

    @classmethod
    def get_price(cls, symbol: str) -> Optional[dict]:
        return cls.latest_prices.get(symbol.upper())


class ForecastExFeeder(BaseFeeder):
    def __init__(self, symbol: str, event_queue: asyncio.Queue):
        super().__init__(symbol, event_queue)
        self.symbol = symbol.upper()
        self.interval = float(os.getenv("FORECASTEX_POLL_INTERVAL", "1.0"))
        self.ib_host = os.getenv("IBKR_HOST", "127.0.0.1")
        self.ib_port = int(os.getenv("IBKR_PORT", "7497"))  # 7497 TWS Paper / 4002 Gateway

    async def start(self):
        """Inicia el conector de ForecastEx (IBKR)."""
        self.running = True
        logger.info(f"[Feeder ForecastEx IBKR] Conectando a IBKR (TWS/Gateway) para mercado {self.symbol}...")
        asyncio.create_task(self._poll_prices())

    async def _poll_prices(self):
        # ForecastEx/IBKR connector — NOT IMPLEMENTED
        # This feeder requires ib_async library and a running TWS/Gateway instance
        # It will NOT emit any prices until properly connected to IBKR
        logger.error(
            f"[Feeder ForecastEx IBKR] NO IMPLEMENTADO — este feeder requiere "
            f"ib_async y TWS/Gateway corriendo. No se emitirán precios falsos."
        )
        self.running = False

    async def stop(self):
        """Detiene el feeder de ForecastEx."""
        self.running = False
        logger.info(f"[Feeder ForecastEx IBKR] Detenido para {self.symbol}.")
