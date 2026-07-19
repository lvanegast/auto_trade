"""
Limitless Exchange Feeder — obtiene precios de mercados de predicción en tiempo real.

Usa el SDK oficial limitless-sdk para fetch markets, orderbooks y precios.
Polling cada N segundos (Limitless no tiene WebSocket público sin auth para lectura).

For group markets (NegRisk): scans ALL child outcomes and computes 1×N arb edge.
"""

import asyncio
import os
import time
from src.feeders.base import BaseFeeder
from src.events import PriceUpdateEvent


# Shared macro edge data: feeder writes, cross-platform arb strategy reads
# {event_id: {"total_yes": float, "edge": float, "outcomes": [...], "title": str, "group_slug": str}}
_macro_edge_data: dict = {}


def update_macro_edge(
    event_id: str,
    total_yes: float,
    edge: float,
    outcomes: list,
    title: str = "",
    group_slug: str = "",
):
    """Called by LimitlessFeeder to pass macro group data to the strategy."""
    _macro_edge_data[event_id] = {
        "total_yes": total_yes,
        "edge": edge,
        "outcomes": outcomes,
        "title": title,
        "group_slug": group_slug,
    }


def get_macro_edge_data() -> dict:
    """Read-only access for strategies."""
    return _macro_edge_data


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
        subs = group_market.markets if hasattr(group_market, "markets") and group_market.markets else []

        if subs:
            # Group market: scan ALL children for 1×N arb
            await self._handle_group_market(market_fetcher, group_market, subs, slug)
        else:
            # Single market: just emit price
            await self._handle_single_market(market_fetcher, group_market, slug)

    async def _handle_group_market(self, market_fetcher, group_market, subs, parent_slug):
        """Scan all child outcomes, compute 1×N edge, emit price."""
        total_yes = 0
        outcomes = []
        has_liquidity = False

        for sub in subs:
            prices = sub.prices if hasattr(sub, "prices") else [0.5, 0.5]
            yes_price = float(prices[0]) if prices else 0.5
            sub_slug = sub.slug if hasattr(sub, "slug") else ""
            title = sub.title if hasattr(sub, "title") else ""

            if yes_price > 0.01 and yes_price < 0.99:
                has_liquidity = True

            total_yes += yes_price
            outcomes.append({
                "slug": sub_slug,
                "title": title,
                "yes_price": yes_price,
                "no_price": round(1.0 - yes_price, 6),
            })

        if not has_liquidity or len(outcomes) < 2:
            # Fallback: just first child price
            sub = subs[0]
            prices = sub.prices if hasattr(sub, "prices") else [0.5, 0.5]
            yes_price = prices[0] if len(prices) > 0 else 0.5
            await self._emit_price(sub.slug if hasattr(sub, "slug") else parent_slug, yes_price)
            return

        edge = 1.0 - total_yes
        event_id = f"limitless_macro_{parent_slug}"
        primary_price = outcomes[0]["yes_price"]

        # Store macro edge data for cross-platform arb strategy
        update_macro_edge(
            event_id=event_id,
            total_yes=total_yes,
            edge=edge,
            outcomes=outcomes,
            title=group_market.title if hasattr(group_market, "title") else parent_slug,
            group_slug=parent_slug,
        )

        if abs(edge) > 0.02:
            arb_type = "YES" if edge > 0 else "NO"
            print(
                f"[Macro ARB {arb_type}] {parent_slug} | "
                f"Total YES={total_yes:.4f} | Edge={edge:+.2%} | "
                f"{len(outcomes)} outcomes"
            )

        # Emit price for strategy (uses first child's price as reference)
        await self._emit_price(parent_slug, primary_price)

    async def _handle_single_market(self, market_fetcher, market, slug):
        """Handle a single (non-group) market."""
        prices = market.prices if hasattr(market, "prices") else [0.5, 0.5]
        yes_price = prices[0] if len(prices) > 0 else 0.5
        actual_slug = slug

        try:
            orderbook = await market_fetcher.get_orderbook(actual_slug)
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

    async def _emit_price(self, slug, price):
        """Emit a PriceUpdateEvent with bid/ask from orderbook."""
        from limitless_sdk.api import HttpClient
        from limitless_sdk.markets import MarketFetcher

        bid, ask = price, price
        try:
            http_client = HttpClient()
            market_fetcher = MarketFetcher(http_client)
            orderbook = await market_fetcher.get_orderbook(slug)
            bids = orderbook.bids if hasattr(orderbook, "bids") else []
            asks = orderbook.asks if hasattr(orderbook, "asks") else []
            bid = bids[0].price if bids else price
            ask = asks[0].price if asks else price
            await http_client.close()
        except Exception:
            pass

        event = PriceUpdateEvent(
            symbol=self.symbol,
            price=float(price),
            ask=float(ask),
            bid=float(bid),
        )
        await self.queue.put(event)
