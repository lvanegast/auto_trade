"""
Binary Arbitrage Feeder — scans Limitless crypto markets for YES+NO < $1.00.

Polls order books of active BTC/ETH/SOL 5min/15min/hourly markets.
When best_ask(YES) + best_ask(NO) < 1.00 - fees, emits a PriceUpdateEvent.
"""

import asyncio
import os
import time
from src.feeders.base import BaseFeeder
from src.events import PriceUpdateEvent


class BinaryArbFeeder(BaseFeeder):
    def __init__(self, symbol: str, event_queue: asyncio.Queue):
        super().__init__(symbol.upper(), event_queue)
        self.poll_interval = float(os.getenv("BINARY_ARB_POLL_INTERVAL", "2"))
        self.min_spread = float(os.getenv("BINARY_ARB_MIN_SPREAD", "0.01"))
        self.fee_rate = float(os.getenv("BINARY_ARB_FEE_RATE", "0.02"))
        self.task = None
        self._seen_opps = {}
        self._cooldown_seconds = float(os.getenv("BINARY_ARB_COOLDOWN", "10"))

    async def start(self):
        self.running = True
        print(
            f"[Binary Arb Feeder] Iniciando polling cada {self.poll_interval}s "
            f"(min_spread={self.min_spread}, fee={self.fee_rate})"
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

        http_client = HttpClient()

        try:
            while self.running:
                try:
                    await _scan_all_markets(http_client, self)
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    print(f"[Binary Arb] Error: {e}")
                await asyncio.sleep(self.poll_interval)
        finally:
            await http_client.close()


async def _scan_all_markets(http_client, feeder):
    """Scan all active crypto up/down markets for binary arb."""
    from limitless_sdk.markets import MarketFetcher
    mf = MarketFetcher(http_client)
    resp = await mf.get_active_markets()
    markets = resp.data if hasattr(resp, "data") else []

    for m in markets:
        m_slug = m.slug if hasattr(m, "slug") else ""
        title = m.title if hasattr(m, "title") else ""

        if not any(
            kw in m_slug.lower()
            for kw in ["up-or-down", "btc", "eth", "sol", "xrp", "bnb", "hype"]
        ):
            continue

        now = time.time()
        if m_slug in feeder._seen_opps:
            if now - feeder._seen_opps[m_slug] < feeder._cooldown_seconds:
                continue

        try:
            yes_ob = await http_client.get(f"/markets/{m_slug}/orderbook")
            no_ob = await http_client.get(f"/markets/{m_slug}/orderbook?side=NO")
        except Exception:
            continue

        yes_asks = yes_ob.get("asks", []) if isinstance(yes_ob, dict) else []
        no_asks = no_ob.get("asks", []) if isinstance(no_ob, dict) else []

        if not yes_asks or not no_asks:
            continue

        best_yes_ask = float(yes_asks[0]["price"])
        best_yes_size = float(yes_asks[0].get("size", 0))
        best_no_ask = float(no_asks[0]["price"])
        best_no_size = float(no_asks[0].get("size", 0))

        pair_cost = best_yes_ask + best_no_ask
        gross_spread = 1.0 - pair_cost
        fee_cost = feeder.fee_rate * 2
        net_spread = gross_spread - fee_cost

        if net_spread >= feeder.min_spread:
            feeder._seen_opps[m_slug] = now
            min_size = min(best_yes_size, best_no_size)

            print(
                f"[Binary ARB] {title} | "
                f"YES ask={best_yes_ask:.4f} NO ask={best_no_ask:.4f} | "
                f"Pair={pair_cost:.4f} Gross={gross_spread:+.4f} Net={net_spread:+.4f} | "
                f"Size={min_size:.0f}"
            )

            event = PriceUpdateEvent(
                symbol=m_slug,
                price=pair_cost,
                ask=pair_cost,
                bid=pair_cost,
            )

            event._arb_data = {
                "type": "binary",
                "yes_ask": best_yes_ask,
                "no_ask": best_no_ask,
                "pair_cost": pair_cost,
                "gross_spread": gross_spread,
                "net_spread": net_spread,
                "yes_size": best_yes_size,
                "no_size": best_no_size,
                "min_size": min_size,
                "title": title,
                "slug": m_slug,
            }

            await feeder.queue.put(event)
