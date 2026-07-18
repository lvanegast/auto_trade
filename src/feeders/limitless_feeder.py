"""
Limitless Exchange Feeder — obtiene precios de mercados de predicción en tiempo real.

Usa el SDK oficial limitless-sdk para fetch markets, orderbooks y precios.
Polling cada N segundos (Limitless no tiene WebSocket público sin auth para lectura).
"""

import asyncio
import os
import time
from src.feeders.base import BaseFeeder
from src.events import PriceUpdateEvent


class LimitlessFeeder(BaseFeeder):
    def __init__(self, symbol: str, event_queue: asyncio.Queue):
        super().__init__(symbol.upper(), event_queue)
        self.poll_interval = float(os.getenv("LIMITLESS_POLL_INTERVAL", "3"))
        self.task = None
        self._market_cache = {}

    async def start(self):
        self.running = True
        print(
            f"[Feeder Limitless] Iniciando polling cada {self.poll_interval}s para {self.symbol}..."
        )
        self.task = asyncio.create_task(self._run_polling())
        while self.running:
            await asyncio.sleep(1)

    async def stop(self):
        self.running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
            self.task = None

    async def _run_polling(self):
        from limitless_sdk.api import HttpClient
        from limitless_sdk.markets import MarketFetcher

        http_client = HttpClient()
        market_fetcher = MarketFetcher(http_client)

        try:
            while self.running:
                try:
                    await self._fetch_and_emit(market_fetcher)
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    print(f"[Feeder Limitless] Error fetching {self.symbol}: {e}")
                await asyncio.sleep(self.poll_interval)
        finally:
            await http_client.close()

    async def _fetch_and_emit(self, market_fetcher):
        slug = self.symbol.lower()

        if slug not in self._market_cache:
            market = await market_fetcher.get_market(slug)
            self._market_cache[slug] = market
        else:
            market = self._market_cache[slug]

        group_market = market
        if hasattr(group_market, "markets") and group_market.markets:
            sub = group_market.markets[0]
            prices = sub.prices if hasattr(sub, "prices") else [0.5, 0.5]
            yes_price = prices[0] if len(prices) > 0 else 0.5
            slug = sub.slug if hasattr(sub, "slug") else slug
        else:
            prices = group_market.prices if hasattr(group_market, "prices") else [0.5, 0.5]
            yes_price = prices[0] if len(prices) > 0 else 0.5

        try:
            orderbook = await market_fetcher.get_orderbook(slug)
            bids = orderbook.bids if hasattr(orderbook, "bids") else []
            asks = orderbook.asks if hasattr(orderbook, "asks") else []
            bid = bids[0].price if bids else yes_price
            ask = asks[0].price if asks else yes_price
        except Exception:
            bid = yes_price
            ask = yes_price

        event = PriceUpdateEvent(
            symbol=self.symbol,
            price=float(yes_price),
            ask=float(ask),
            bid=float(bid),
        )
        await self.queue.put(event)
