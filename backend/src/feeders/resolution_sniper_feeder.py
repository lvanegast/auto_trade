"""
Resolution Sniper Feeder — Monitors Limitless sports markets for near-certain outcomes.

Scans markets where YES price > 0.95 (95%+ probability).
These are markets where one outcome is almost guaranteed.
Strategy: Buy YES at 95-98¢, hold until resolution, receive $1.00.
"""

import asyncio
import os
import time
from src.feeders.base import BaseFeeder
from src.events import PriceUpdateEvent


# Shared cache to prevent rate limiting
_last_sniper_scan_time = 0.0
_sniper_scan_lock = asyncio.Lock()


class ResolutionSniperFeeder(BaseFeeder):
    def __init__(self, symbol: str, event_queue: asyncio.Queue):
        super().__init__(symbol.upper(), event_queue)
        self.poll_interval = float(os.getenv("SNIPER_POLL_INTERVAL", "5.0"))
        self.min_entry_price = float(os.getenv("SNIPER_MIN_ENTRY_PRICE", "0.95"))
        self.max_entry_price = float(os.getenv("SNIPER_MAX_ENTRY_PRICE", "0.98"))
        self.task = None

    async def start(self):
        self.running = True
        print(
            f"[Feeder Resolution Sniper] Iniciando polling cada {self.poll_interval}s | "
            f"Rango: {self.min_entry_price:.2f} - {self.max_entry_price:.2f}"
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
        from limitless_sdk.markets import MarketFetcher

        http_client = HttpClient()
        self._page_fetcher = MarketPageFetcher(http_client)
        self._market_fetcher = MarketFetcher(http_client)

        try:
            while self.running:
                try:
                    await self._scan_for_snipers()
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    print(f"[Feeder Resolution Sniper] Error: {e}")
                await asyncio.sleep(self.poll_interval)
        finally:
            await http_client.close()

    async def _scan_for_snipers(self):
        global _last_sniper_scan_time
        now = time.time()
        if now - _last_sniper_scan_time < 5.0:
            return
        async with _sniper_scan_lock:
            _last_sniper_scan_time = now
            try:
                from src.engine.latency_tracker import latency_tracker

                page_ids = [
                    "5e76699e-8763-4c91-85de-3efeb064efec",  # Crypto only
                ]

                markets = []
                for page_id in page_ids:
                    try:
                        async with latency_tracker.measure("resolution_sniper", "get_markets") as m:
                            resp = await self._page_fetcher.get_markets(page_id, {"limit": 50})
                            m.result = resp

                        page_m = resp.data if hasattr(resp, "data") else (resp.get("data", []) if isinstance(resp, dict) else [])
                        markets.extend(page_m)
                    except Exception as pe:
                        if "TimeoutError" not in str(type(pe)) and "Cannot connect" not in str(pe):
                            print(f"[Resolution Sniper] Error fetching page {page_id}: {pe}")

                snipers_found = 0
                for m in markets:
                    slug = m.slug if hasattr(m, "slug") else (m.get("slug", "") if isinstance(m, dict) else "")
                    title = m.title if hasattr(m, "title") else (m.get("title", "") if isinstance(m, dict) else "")
                    if not slug:
                        continue

                    # FILTER: Only process crypto markets (limitless_crypto_ prefix)
                    # Skip sports markets
                    if "crypto" not in slug.lower() and "up-or-down" not in slug.lower():
                        continue

                    # Check for single/binary markets
                    from src.limitless_price_cache import async_get_limitless_executable_price
                    book = await async_get_limitless_executable_price(slug)
                    if book:
                        yes_price = book["yes_ask"]
                        if self.min_entry_price <= yes_price <= self.max_entry_price and book["ask_size"] > 0:
                            snipers_found += 1
                            print(f"[Resolution Sniper] Found: {title[:50]} YES_ASK={yes_price:.4f}")
                            await self._emit_sniper_signal(slug, title, yes_price)

                    # Check sub-markets in groups
                    subs = getattr(m, "markets", None) or (m.get("markets") if isinstance(m, dict) else None)
                    if subs and isinstance(subs, list):
                        for sub in subs:
                            sub_slug = getattr(sub, "slug", "") if hasattr(sub, "slug") else (sub.get("slug", "") if isinstance(sub, dict) else "")
                            sub_title = getattr(sub, "title", "") if hasattr(sub, "title") else (sub.get("title", "") if isinstance(sub, dict) else "")
                            sub_prices = getattr(sub, "prices", None) if hasattr(sub, "prices") else (sub.get("prices") if isinstance(sub, dict) else None)

                            from src.limitless_price_cache import async_get_limitless_executable_price
                            sub_book = await async_get_limitless_executable_price(sub_slug)
                            if sub_book:
                                sub_yes_price = sub_book["yes_ask"]
                                if self.min_entry_price <= sub_yes_price <= self.max_entry_price and sub_book["ask_size"] > 0:
                                    snipers_found += 1
                                    print(f"[Resolution Sniper] Found: {sub_title[:50]} YES_ASK={sub_yes_price:.4f}")
                                    await self._emit_sniper_signal(sub_slug, sub_title, sub_yes_price)

                    # Delay between markets
                    await asyncio.sleep(0.1)

                print(f"[Resolution Sniper] Scan complete: {len(markets)} markets checked, {snipers_found} snipers found")

            except Exception as e:
                print(f"[Resolution Sniper] Error scanning: {e}")

    async def _check_liquidity(self, slug: str) -> bool:
        """Check if market has real liquidity (bids and asks)."""
        try:
            from limitless_sdk.markets import MarketFetcher
            from limitless_sdk.api import HttpClient

            async with HttpClient() as http:
                fetcher = MarketFetcher(http)
                ob = await fetcher.get_orderbook(slug)
                bids = ob.bids if hasattr(ob, 'bids') else []
                asks = ob.asks if hasattr(ob, 'asks') else []

                # Need at least some liquidity on both sides
                return len(bids) > 0 and len(asks) > 0
        except Exception:
            return False

    async def _emit_sniper_signal(self, slug: str, title: str, yes_price: float):
        """Emit a PriceUpdateEvent for the strategy to process."""
        from src.strategy.resolution_sniper import update_sniper_data

        event_id = f"limitless_sniper_{slug}"

        # Update strategy data
        update_sniper_data(
            event_id=event_id,
            yes_price=yes_price,
            title=title,
            slug=slug,
            sport="sports",
        )

        # Create and emit price event
        event = PriceUpdateEvent(
            symbol=event_id,
            price=yes_price,
            ask=yes_price,
            bid=yes_price,
        )
        await self.queue.put(event)
