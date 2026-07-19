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


class LimitlessSportsFeeder(BaseFeeder):
    def __init__(self, symbol: str, event_queue: asyncio.Queue):
        super().__init__(symbol.upper(), event_queue)
        self.poll_interval = float(os.getenv("SPORTS_POLL_INTERVAL", "10"))
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
        from src.strategy.cross_platform_tracker import cross_platform_tracker

        sport_categories = [
            "2a91349c-3308-4234-afb7-0663e42968c1",
            "746c37e2-9d57-4e57-8527-7b1ae4817fb8",
        ]

        for cat_id in sport_categories:
            try:
                resp = await self._page_fetcher.get_markets(
                    cat_id, {"limit": 25}
                )
                markets = resp.data if hasattr(resp, "data") else resp.get("data", [])

                for m in markets:
                    slug = m.slug if hasattr(m, "slug") else m.get("slug", "")
                    title = m.title if hasattr(m, "title") else m.get("title", "")
                    vol = getattr(m, "volume_formatted", None) or "0"

                    try:
                        vol_float = float(vol) if vol else 0
                    except (ValueError, TypeError):
                        vol_float = 0

                    if vol_float < self.min_volume:
                        continue

                    await self._check_group_arb(slug, title)

            except Exception as e:
                print(f"[Sports] Error scanning category: {e}")

    async def _check_group_arb(self, group_slug, group_title):
        from src.strategy.cross_platform_tracker import cross_platform_tracker

        try:
            market = await self._market_fetcher.get_market(group_slug)
        except Exception:
            return

        subs = market.markets if hasattr(market, "markets") and market.markets else []
        if len(subs) < 2:
            return

        total_yes = 0
        outcomes = []
        has_liquidity = False

        for sub in subs:
            prices = sub.prices if hasattr(sub, "prices") else [0.5, 0.5]
            yes_price = float(prices[0]) if prices else 0.5
            slug = sub.slug if hasattr(sub, "slug") else ""
            title = sub.title if hasattr(sub, "title") else ""

            if yes_price > 0.01 and yes_price < 0.99:
                has_liquidity = True

            total_yes += yes_price
            outcomes.append({
                "slug": slug,
                "title": title,
                "yes_price": yes_price,
                "no_price": 1.0 - yes_price,
            })

        if not has_liquidity:
            return

        edge = 1.0 - total_yes

        event_id = f"limitless_sport_{group_slug}"
        primary_price = outcomes[0]["yes_price"] if outcomes else 0.5

        cross_platform_tracker.update_price(
            event_id=event_id,
            platform="limitless",
            price=primary_price,
            bid=primary_price,
            ask=primary_price,
        )

        # Pass edge data to the sports arb strategy (with full outcomes)
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

        if edge > 0.02:
            print(
                f"[Sports ARB YES] {group_title} | "
                f"Total YES={total_yes:.4f} | Edge={edge:+.2%} | "
                f"{len(outcomes)} outcomes | BUY ALL YES"
            )

            event = PriceUpdateEvent(
                symbol=event_id,
                price=primary_price,
                ask=primary_price,
                bid=primary_price,
            )
            await self.queue.put(event)

        elif edge < -0.02:
            print(
                f"[Sports ARB NO] {group_title} | "
                f"Total YES={total_yes:.4f} | Overedge={edge:+.2%} | "
                f"{len(outcomes)} outcomes | BUY ALL NO"
            )

            event = PriceUpdateEvent(
                symbol=event_id,
                price=primary_price,
                ask=primary_price,
                bid=primary_price,
            )
            await self.queue.put(event)
