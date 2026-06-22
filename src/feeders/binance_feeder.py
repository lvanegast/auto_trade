import asyncio
import json
import urllib.request
from src.feeders.base import BaseFeeder
from src.events import PriceUpdateEvent


class BinanceFeeder(BaseFeeder):
    def __init__(self, symbol: str, event_queue: asyncio.Queue, interval: float = 2.0):
        # El símbolo viene en formato BNB/USDT o similar
        self.symbol_raw = symbol.upper()
        # Limpiar para la API de Binance (BNB/USDT -> BNBUSDT)
        self.binance_symbol = self.symbol_raw.replace("/", "")
        super().__init__(symbol, event_queue)
        self.interval = interval

    def _fetch_ticker(self):
        """Llamada síncrona a la API pública de Binance."""
        url = f"https://api.binance.com/api/v3/ticker/bookTicker?symbol={self.binance_symbol}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))

    async def start(self):
        self.running = True
        print(f"[Feeder Binance] Iniciada recolección pública para {self.symbol}...")

        while self.running:
            try:
                # Realizar llamada bloqueante en un hilo secundario para no congelar el loop
                data = await asyncio.to_thread(self._fetch_ticker)

                bid = float(data.get("bidPrice", 0.0))
                ask = float(data.get("askPrice", 0.0))
                price = round((bid + ask) / 2.0, 4)

                event = PriceUpdateEvent(
                    symbol=self.symbol, price=price, ask=ask, bid=bid
                )

                await self.queue.put(event)

            except Exception as e:
                print(
                    f"[Feeder Binance] Error al obtener cotización para {self.symbol}: {e}"
                )

            await asyncio.sleep(self.interval)
