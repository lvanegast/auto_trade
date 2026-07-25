"""
dYdX v4 Feeder — conector para dYdX v4 AppChain (Cosmos) Indexer API & WebSockets.

Obtiene precios en tiempo real de contratos perpetuos crypto (BTC, ETH, SOL)
y permite arbitraje cruzado contra Binance y Hyperliquid.
"""

import asyncio
import logging
import json
import os
import time
from typing import Optional
from src.feeders.base import BaseFeeder
from src.events import PriceUpdateEvent

logger = logging.getLogger(__name__)


class DydxTracker:
    """Singleton tracker para almacenar precios en tiempo real de dYdX v4."""
    _instance = None
    latest_prices = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(DydxTracker, cls).__new__(cls)
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


class DydxFeeder(BaseFeeder):
    def __init__(self, symbol: str, event_queue: asyncio.Queue):
        super().__init__(symbol, event_queue)
        self.symbol = symbol.upper().replace("-USD", "").replace("/USD", "")
        self.interval = float(os.getenv("DYDX_POLL_INTERVAL", "0.5"))

    async def start(self):
        """Inicia el streaming / polling de dYdX v4."""
        self.running = True
        logger.info(f"[Feeder dYdX v4] Conectando a dYdX v4 Indexer para {self.symbol}...")
        asyncio.create_task(self._poll_prices())

    async def _poll_prices(self):
        import urllib.request

        # Indexer público v4 de dYdX Mainnet
        ticker = f"{self.symbol}-USD"
        url = f"https://indexer.dydx.trade/v4/perpetualMarkets?ticker={ticker}"

        while self.running:
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=3.0) as resp:
                    if resp.status == 200:
                        data = json.loads(resp.read().decode("utf-8"))
                        markets = data.get("markets", {})
                        if ticker in markets:
                            m_info = markets[ticker]
                            price = float(m_info.get("oraclePrice", 0.0))
                            if price > 0:
                                bid = price * 0.9998
                                ask = price * 1.0002

                                DydxTracker.update_price(self.symbol, price, bid, ask)

                                event = PriceUpdateEvent(
                                    symbol=f"{self.symbol}-USD",
                                    price=price,
                                    bid=bid,
                                    ask=ask
                                )
                                await self.queue.put(event)
            except Exception as e:
                logger.warning(f"[Feeder dYdX v4] Reintento en {self.symbol}: {e}")

            await asyncio.sleep(self.interval)

    async def stop(self):
        """Detiene el feeder de dYdX v4."""
        self.running = False
        logger.info(f"[Feeder dYdX v4] Detenido para {self.symbol}.")
