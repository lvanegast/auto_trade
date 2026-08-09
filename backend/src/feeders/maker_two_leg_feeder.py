"""
Maker Two-Leg Feeder (Worker 6) — Escanea mercados binarios up-or-down en Limitless
y emite PriceUpdateEvent con el BOOK REAL (bid/ask ejecutables) para cada mercado.

A diferencia del ResolutionSniperFeeder (que solo busca YES~0.98), este feeder NO
filtra por precio: la estrategia MakerTwoLegStrategy decide el edge (spread) sobre
el book. Aquí el edge vive en la profundidad del spread, no en el precio absoluto.

Emit events: symbol="limitless_crypto_{slug}", bid=yes_bid, ask=yes_ask,
bid_size=profundidad bids, ask_size=profundidad asks.
"""

import asyncio
import os
import time
from src.feeders.base import BaseFeeder
from src.events import PriceUpdateEvent


# Shared cache to prevent rate limiting
_last_maker_scan_time = 0.0
_maker_scan_lock = asyncio.Lock()


class MakerTwoLegFeeder(BaseFeeder):
    def __init__(self, symbol: str, event_queue: asyncio.Queue):
        super().__init__(symbol.upper(), event_queue)
        self.poll_interval = float(os.getenv("MAKER_POLL_INTERVAL", "5.0"))
        self.page_ids = [
            "5e76699e-8763-4c91-85de-3efeb064efec",  # Crypto only
        ]
        self.task = None

    async def start(self):
        self.running = True
        print(
            f"[Feeder Maker 2-Leg] Iniciando polling cada {self.poll_interval}s | "
            f"Páginas: {len(self.page_ids)} (crypto up-or-down)"
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
        from limitless_sdk.market_pages import MarketPageFetcher

        http_client = HttpClient()
        self._page_fetcher = MarketPageFetcher(http_client)

        try:
            while self.running:
                try:
                    await self._scan_markets()
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    print(f"[Feeder Maker 2-Leg] Error: {e}")
                await asyncio.sleep(self.poll_interval)
        finally:
            await http_client.close()

    async def _scan_markets(self):
        global _last_maker_scan_time
        now = time.time()
        if now - _last_maker_scan_time < 5.0:
            return
        async with _maker_scan_lock:
            _last_maker_scan_time = now
            try:
                from src.engine.latency_tracker import latency_tracker

                markets = []
                for page_id in self.page_ids:
                    try:
                        async with latency_tracker.measure("maker_two_leg", "get_markets") as m:
                            resp = await self._page_fetcher.get_markets(page_id, {"limit": 50})
                            m.result = resp
                        page_m = resp.data if hasattr(resp, "data") else (resp.get("data", []) if isinstance(resp, dict) else [])
                        markets.extend(page_m)
                    except Exception as pe:
                        if "TimeoutError" not in str(type(pe)) and "Cannot connect" not in str(pe):
                            print(f"[Maker 2-Leg] Error fetching page {page_id}: {pe}")

                scanned = 0
                for m in markets:
                    slug = m.slug if hasattr(m, "slug") else (m.get("slug", "") if isinstance(m, dict) else "")
                    title = m.title if hasattr(m, "title") else (m.get("title", "") if isinstance(m, dict) else "")
                    if not slug:
                        continue

                    # FILTER: solo mercados binarios crypto up-or-down (2 patas)
                    if "crypto" not in slug.lower() and "up-or-down" not in slug.lower():
                        continue

                    scanned += 1

                    # Volumen real transado (USD) — el indicador de "vivo".
                    # La profundidad del book (millones de shares) es postura lejana;
                    # un mercado con volumen ~0 jamás llena 2 patas maker.
                    volume_raw = m.volume_formatted if hasattr(m, "volume_formatted") else (m.get("volume_formatted", "") if isinstance(m, dict) else "")
                    try:
                        market_volume = float(volume_raw) if volume_raw else 0.0
                    except (TypeError, ValueError):
                        market_volume = 0.0

                    # Book real (bid/ask ejecutables)
                    from src.limitless_price_cache import async_get_limitless_executable_price
                    book = await async_get_limitless_executable_price(slug)
                    if not book:
                        continue

                    yes_bid = book.get("yes_bid", 0.0)
                    yes_ask = book.get("yes_ask", 0.0)
                    bid_size = book.get("bid_size", 0.0)
                    ask_size = book.get("ask_size", 0.0)
                    if yes_bid <= 0 or yes_ask <= 0 or yes_ask <= yes_bid:
                        continue

                    event = PriceUpdateEvent(
                        symbol=f"limitless_crypto_{slug}",
                        price=round((yes_bid + yes_ask) / 2.0, 4),
                        ask=round(yes_ask, 4),
                        bid=round(yes_bid, 4),
                        chart_price=title,
                    )
                    event.bid_size = bid_size
                    event.ask_size = ask_size
                    event.market_slug = slug
                    event.title = title
                    event.market_volume = market_volume
                    await self.queue.put(event)

                    # Delay entre markets para no saturar la API
                    await asyncio.sleep(0.05)

                print(f"[Maker 2-Leg] Scan completo: {len(markets)} markets, {scanned} crypto, "
                      f"books emitidos OK")

            except Exception as e:
                print(f"[Maker 2-Leg] Error scanning: {e}")
