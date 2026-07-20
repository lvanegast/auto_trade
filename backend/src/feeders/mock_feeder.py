import asyncio
import random
import math
from src.feeders.base import BaseFeeder
from src.events import PriceUpdateEvent


class MockFeeder(BaseFeeder):
    def __init__(self, symbol: str, event_queue: asyncio.Queue, interval: float = 1.0):
        super().__init__(symbol, event_queue)
        self.interval = interval
        self.base_price = 100.0
        self.counter = 0

    async def start(self):
        self.running = True
        print(
            f"[Feeder] Simulación iniciada para {self.symbol} (intervalo: {self.interval}s)"
        )

        while self.running:
            # Crear un movimiento senoidal con ruido aleatorio para cruzar EMAs constantemente
            self.counter += 1
            trend = 5.0 * math.sin(self.counter * 0.15)
            noise = random.uniform(-0.2, 0.2)
            current_price = round(self.base_price + trend + noise, 4)

            # Generar el evento
            event = PriceUpdateEvent(
                symbol=self.symbol,
                price=current_price,
                ask=round(current_price + 0.02, 4),
                bid=round(current_price - 0.02, 4),
            )

            # Enviar el evento a la cola
            await self.queue.put(event)

            # Dormir hasta el siguiente ciclo
            await asyncio.sleep(self.interval)
