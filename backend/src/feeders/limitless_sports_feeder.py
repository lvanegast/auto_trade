"""
Limitless Sports Feeder — monitorea mercados deportivos de Limitless Exchange.

Descubre mercados con liquidity, calcula arbitraje intra-platform
cuando los precios de todos los outcomes no suman 1.0.

Ejemplo de arbitraje intra-platform:
  "Method of Victory" = 6 outcomes:
    Spain Win Reg Time:  0.35
    Argentina Win Reg:   0.30
    Spain Win ET:        0.10
    Argentina Win ET:    0.08
    Spain Win Pen:       0.10
    Argentina Win Pen:   0.08
    TOTAL = 1.01 → sin arbitraje

  Si TOTAL < 1.0 → comprar TODOS los outcomes = profit garantizado
  Si TOTAL > 1.0 → vender todos = profit garantizado (necesitas tener positions)
"""

import asyncio
import os
import time
from src.feeders.base import BaseFeeder
from src.events import PriceUpdateEvent


import time

# Shared cache to prevent Cloudflare HTTP 429 rate limit across multiple worker feeders
_last_sports_scan_time = 0.0
_sports_scan_lock = asyncio.Lock()


class LimitlessSportsFeeder(BaseFeeder):
    def __init__(self, symbol: str, event_queue: asyncio.Queue):
        super().__init__(symbol.upper(), event_queue)
        self.poll_interval = float(os.getenv("SPORTS_POLL_INTERVAL", "3.0"))
        self.min_volume = float(os.getenv("SPORTS_MIN_VOLUME", "100"))
        self.task = None

    async def start(self):
        self.running = True
        print(
            f"[Feeder Limitless Sports] Iniciando polling cada {self.poll_interval}s..."
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
                    await self._scan_sports_markets()
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    print(f"[Feeder Limitless Sports] Error: {e}")
                await asyncio.sleep(self.poll_interval)
        finally:
            await http_client.close()

    async def _scan_sports_markets(self):
        global _last_sports_scan_time
        now = time.time()
        if now - _last_sports_scan_time < 5.0:
            return
        async with _sports_scan_lock:
            _last_sports_scan_time = now
            try:
                page_ids = [
                    "2a91349c-3308-4234-afb7-0663e42968c1",  # Sport
                    "f2a04a4e-580a-4cd1-bcc9-c23ed9ff8916",  # Esports
                ]
                
                markets = []
                for page_id in page_ids:
                    try:
                        resp = await self._page_fetcher.get_markets(page_id, {"limit": 30})
                        page_m = resp.data if hasattr(resp, "data") else (resp.get("data", []) if isinstance(resp, dict) else [])
                        markets.extend(page_m)
                    except Exception as pe:
                        print(f"[Sports Feeder] Error fetching page {page_id}: {pe}")

                print(f"[Sports Feeder] Fetched {len(markets)} markets from {len(page_ids)} pages")
                for m in markets:
                    slug = m.slug if hasattr(m, "slug") else (m.get("slug", "") if isinstance(m, dict) else "")
                    title = m.title if hasattr(m, "title") else (m.get("title", "") if isinstance(m, dict) else "")
                    if not slug:
                        continue

                    # Extract sub-markets directly from item payload without secondary HTTP request
                    subs = getattr(m, "markets", None) or (m.get("markets") if isinstance(m, dict) else None)
                    if subs and isinstance(subs, list) and len(subs) >= 2:
                        await self._process_group_arb(slug, title, subs)
                    else:
                        # Single / binary market directly in item
                        prices = getattr(m, "prices", None) or (m.get("prices") if isinstance(m, dict) else None)
                        if prices and len(prices) >= 2:
                            await self._process_single_market(slug, title, prices)
                    
                    # Delay entre mercados para evitar rate limiting
                    await asyncio.sleep(0.1)

                print(f"[Sports Feeder] Scan complete: {len(markets)} markets checked")
            except Exception as e:
                print(f"[Sports] Error escaneando eventos dinámicos: {e}")

    async def _process_group_arb(self, group_slug, group_title, subs):
        from src.strategy.cross_platform_tracker import cross_platform_tracker

        total_subs = len(subs)
        total_yes = 0
        outcomes = []
        has_liquidity = False
        skipped_no_price = 0

        for sub in subs:
            prices = getattr(sub, "prices", None) if hasattr(sub, "prices") else (sub.get("prices") if isinstance(sub, dict) else None)
            if not prices or len(prices) == 0:
                skipped_no_price += 1
                continue
            try:
                yes_price = float(prices[0])
            except (ValueError, TypeError):
                skipped_no_price += 1
                continue

            slug = getattr(sub, "slug", "") if hasattr(sub, "slug") else (sub.get("slug", "") if isinstance(sub, dict) else "")
            title = getattr(sub, "title", "") if hasattr(sub, "title") else (sub.get("title", "") if isinstance(sub, dict) else "")

            if yes_price > 0.01 and yes_price < 0.99:
                has_liquidity = True

            total_yes += yes_price
            outcomes.append(
                {
                    "slug": slug,
                    "title": title,
                    "yes_price": yes_price,
                    "no_price": 1.0 - yes_price,
                }
            )

        if not has_liquidity or len(outcomes) < 2 or skipped_no_price > 0:
            return

        edge = 1.0 - total_yes
        if abs(edge) > 0.15:
            return

        event_id = f"limitless_sport_{group_slug}"
        primary_price = outcomes[0]["yes_price"]

        cross_platform_tracker.update_price(
            event_id=event_id,
            platform="limitless",
            price=primary_price,
            bid=primary_price,
            ask=primary_price,
        )

        from src.strategy.sports_arb import update_sports_edge
        update_sports_edge(
            event_id=event_id,
            total_yes=total_yes,
            edge=edge,
            outcomes_count=len(outcomes),
            title=group_title,
            outcomes=outcomes,
            group_slug=group_slug,
        )

        event = PriceUpdateEvent(
            symbol=event_id,
            price=primary_price,
            ask=primary_price,
            bid=primary_price,
        )
        await self.queue.put(event)

    async def _process_single_market(self, slug, title, prices):
        from src.strategy.cross_platform_tracker import cross_platform_tracker

        try:
            yes_price = float(prices[0])
            no_price = float(prices[1])
        except (ValueError, TypeError, IndexError):
            return

        total_yes = yes_price + no_price
        edge = 1.0 - total_yes
        if abs(edge) > 0.15:
            return

        event_id = f"limitless_sport_{slug}"
        cross_platform_tracker.update_price(
            event_id=event_id,
            platform="limitless",
            price=yes_price,
            bid=yes_price,
            ask=yes_price,
        )

        from src.strategy.sports_arb import update_sports_edge
        outcomes = [
            {"slug": f"{slug}_YES", "title": f"{title} (YES)", "yes_price": yes_price, "no_price": no_price},
            {"slug": f"{slug}_NO", "title": f"{title} (NO)", "yes_price": no_price, "no_price": yes_price},
        ]
        update_sports_edge(
            event_id=event_id,
            total_yes=total_yes,
            edge=edge,
            outcomes_count=2,
            title=title,
            outcomes=outcomes,
            group_slug=slug,
        )

        event = PriceUpdateEvent(
            symbol=event_id,
            price=yes_price,
            ask=yes_price,
            bid=yes_price,
        )
        await self.queue.put(event)
