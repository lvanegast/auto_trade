import asyncio
import json
import urllib.request
from src.feeders.base import BaseFeeder
from src.events import PriceUpdateEvent


class PolymarketFeeder(BaseFeeder):
    def __init__(self, symbol: str, event_queue: asyncio.Queue, interval: float = 2.0):
        # El símbolo en Polymarket es el Token ID (un entero muy grande como string)
        self.token_id = symbol.strip()
        super().__init__(symbol, event_queue)
        self.interval = interval

    def _fetch_book(self):
        """Llamada síncrona a la API pública de Polymarket para obtener el libro."""
        url = f"https://clob.polymarket.com/book?token_id={self.token_id}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))

    async def start(self):
        self.running = True
        print(
            f"[Feeder Polymarket] Iniciada recolección para Token ID: {self.symbol}..."
        )

        while self.running:
            try:
                try:
                    # Realizar llamada en hilo secundario
                    data = await asyncio.to_thread(self._fetch_book)
                    bids = data.get("bids", [])
                    asks = data.get("asks", [])
                    bid = float(bids[0]["price"]) if bids else 0.50
                    ask = float(asks[0]["price"]) if asks else 0.50
                    price = round((bid + ask) / 2.0, 4)
                except Exception as ex:
                    # Si falla (por geobloqueo, red, etc.), simulamos un precio con random walk
                    if not hasattr(self, "_last_sim_price"):
                        self._last_sim_price = 0.50

                    import random

                    drift = random.uniform(-0.01, 0.01)
                    new_price = max(0.01, min(0.99, self._last_sim_price + drift))
                    self._last_sim_price = round(new_price, 4)

                    bid = round(max(0.01, self._last_sim_price - 0.005), 4)
                    ask = round(min(0.99, self._last_sim_price + 0.005), 4)
                    price = self._last_sim_price
                    # Imprimir advertencia pero continuar con la simulación
                    print(
                        f"[Feeder Polymarket] Error API ({ex}). Usando precio simulado: {price}"
                    )

                event = PriceUpdateEvent(
                    symbol=self.symbol, price=price, ask=ask, bid=bid
                )

                await self.queue.put(event)

            except Exception as e:
                print(f"[Feeder Polymarket] Error inesperado en loop Polymarket: {e}")

            await asyncio.sleep(self.interval)
