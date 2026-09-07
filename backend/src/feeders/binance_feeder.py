import asyncio
import logging
from datetime import datetime, timezone
from src.feeders.base import BaseFeeder
from src.feeders.connection_manager import AsyncWebSocketManager
from src.events import PriceUpdateEvent

logger = logging.getLogger("BinanceFeeder")


class _BinanceFeederWebSocket(AsyncWebSocketManager):
    """WebSocket manager for real-time Binance best bid/ask data."""

    def __init__(self, symbol: str, queue: asyncio.Queue, **kwargs):
        self.binance_symbol = symbol.replace("/", "").lower()
        # bookTicker conserva bid/ask para la estrategia; aggTrade aporta el
        # último precio negociado para que la gráfica sí avance con el mercado.
        url = (
            f"wss://stream.binance.com:9443/stream?streams="
            f"{self.binance_symbol}@bookTicker/{self.binance_symbol}@aggTrade"
        )
        super().__init__(url=url, name=f"BinanceFeeder-{symbol}", **kwargs)
        self.queue = queue
        self.symbol = symbol
        self._bid = 0.0
        self._ask = 0.0

    async def on_message(self, data: dict):
        stream = data.get("stream", "")
        ticker = data.get("data", {})
        if not ticker:
            return

        if stream.endswith("@bookTicker"):
            self._bid = float(ticker.get("b", 0.0))
            self._ask = float(ticker.get("a", 0.0))
            bid_qty = float(ticker.get("B", 0.0))
            ask_qty = float(ticker.get("A", 0.0))
            try:
                from src.engine.order_flow_imbalance import ofi_tracker
                ofi_tracker.record_book_ticker(self.symbol, self._bid, bid_qty, self._ask, ask_qty)
            except Exception:
                pass
            price = (
                round((self._bid + self._ask) / 2.0, 4)
                if self._bid > 0 and self._ask > 0
                else self._bid or self._ask
            )
            chart_price = None
            event_time_ms = ticker.get("E")
        elif stream.endswith("@aggTrade"):
            chart_price = float(ticker.get("p", 0.0))
            if chart_price <= 0:
                return
            price = (
                round((self._bid + self._ask) / 2.0, 4)
                if self._bid > 0 and self._ask > 0
                else chart_price
            )
            event_time_ms = ticker.get("T") or ticker.get("E")
        else:
            return

        # Binance incluye la hora del evento en milisegundos. Conservarla
        # evita que una cola o una reconexión desplace velas en el frontend.
        timestamp = (
            datetime.fromtimestamp(float(event_time_ms) / 1000, tz=timezone.utc)
            if event_time_ms
            else None
        )
        event = PriceUpdateEvent(
            symbol=self.symbol,
            price=price,
            ask=self._ask or price,
            bid=self._bid or price,
            timestamp=timestamp,
            chart_price=chart_price,
        )
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
