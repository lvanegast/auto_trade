import asyncio
from abc import ABC, abstractmethod


class BaseFeeder(ABC):
    def __init__(self, symbol: str, event_queue: asyncio.Queue):
        self.symbol = symbol
        self.queue = event_queue
        self.running = False

    @abstractmethod
    async def start(self):
        """Inicia la recolección de datos asíncrona."""
        pass

    async def stop(self):
        """Detiene el feeder."""
        self.running = False
