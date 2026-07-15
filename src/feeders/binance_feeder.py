import asyncio
import json
import logging
from src.feeders.base import BaseFeeder
from src.feeders.connection_manager import AsyncWebSocketManager
from src.events import PriceUpdateEvent

logger = logging.getLogger("BinanceFeeder")


class _BinanceFeederWebSocket(AsyncWebSocketManager):
    """WebSocket manager for real-time Binance best bid/ask data."""

    def __init__(self, symbol: str, queue: asyncio.Queue, **kwargs):
        self.binance_symbol = symbol.replace("/", "").lower()
        url = f"wss://stream.binance.com:9443/stream?streams={self.binance_symbol}@bookTicker"
        super().__init__(url=url, name=f"BinanceFeeder-{symbol}", **kwargs)
        self.queue = queue
        self.symbol = symbol

    async def on_message(self, data: dict):
        stream = data.get("stream", "")
        ticker = data.get("data", {})
        if not ticker:
            return

        bid = float(ticker.get("b", 0.0))
        ask = float(ticker.get("B", 0.0))
        price = round((bid + ask) / 2.0, 4) if bid > 0 and ask > 0 else bid or ask

        event = PriceUpdateEvent(symbol=self.symbol, price=price, ask=ask, bid=bid)
        await self.queue.put(event)


class BinanceFeeder(BaseFeeder):
    def __init__(self, symbol: str, event_queue: asyncio.Queue, interval: float = 2.0):
        self.symbol_raw = symbol.upper()
        self.binance_symbol = self.symbol_raw.replace("/", "")
        super().__init__(symbol, event_queue)
        self.interval = interval
        self._ws_manager = None

    async def start(self):
        self.running = True
        logger.info(f"BinanceFeeder WebSocket iniciado para {self.symbol}...")

        self._ws_manager = _BinanceFeederWebSocket(
            symbol=self.symbol,
            queue=self.queue,
            ping_interval=20,
            ping_timeout=10,
            health_check_timeout=30.0,
        )
        await self._ws_manager.connect()

        # Keep feeder alive while running
        while self.running:
            await asyncio.sleep(1)

    async def stop(self):
        self.running = False
        if self._ws_manager:
            await self._ws_manager.disconnect()
            self._ws_manager = None
        logger.info(f"BinanceFeeder WebSocket detenido para {self.symbol}.")
