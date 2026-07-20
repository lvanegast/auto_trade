"""
Limitless Oracle Momentum Feeder — tracks real-time crypto price via Binance
and compares against Limitless "Up or Down" markets for the SAME asset.

When momentum direction mismatches market pricing → emits signal.
Only trades markets matching the configured symbol.
"""

import asyncio
import os
import time
from collections import deque
from src.feeders.base import BaseFeeder
from src.events import PriceUpdateEvent

SYMBOL_MAP = {
    "BTC": ["btc"],
    "ETH": ["eth"],
    "SOL": ["sol"],
    "DOGE": ["doge"],
    "XRP": ["xrp"],
    "BNB": ["bnb"],
    "BCH": ["bch"],
    "SUI": ["sui"],
    "AVAX": ["avax"],
    "ARB": ["arb"],
    "HYPE": ["hype"],
}


class LimitlessOracleFeeder(BaseFeeder):
    def __init__(self, symbol: str, event_queue: asyncio.Queue):
        super().__init__(symbol.upper(), event_queue)
        self.poll_interval = float(os.getenv("ORACLE_POLL_INTERVAL", "3"))
        self.momentum_window = int(os.getenv("ORACLE_MOMENTUM_WINDOW", "30"))
        self.min_momentum_pct = float(os.getenv("ORACLE_MIN_MOMENTUM_PCT", "0.05"))
        self.min_edge_pct = float(os.getenv("ORACLE_MIN_EDGE_PCT", "0.08"))
        self.task = None
        self._price_history = deque(maxlen=200)
        self._binance_price = 0.0
        self._binance_task = None
        self._seen_markets = {}
        self._cooldown = float(os.getenv("ORACLE_MARKET_COOLDOWN", "30"))
        self._base_asset = self._extract_base()
        self._max_signals_per_scan = int(os.getenv("ORACLE_MAX_SIGNALS", "3"))

    def _extract_base(self):
        sym = self.symbol.replace("/USD", "").replace("/USDC", "").upper()
        for key in SYMBOL_MAP:
            if key in sym:
                return key
        return sym[:3]

    async def start(self):
        self.running = True
        print(
            f"[Oracle Feeder] Iniciando | symbol={self.symbol} | "
            f"base_asset={self._base_asset} | poll={self.poll_interval}s | "
            f"momentum_window={self.momentum_window}s | "
            f"min_momentum={self.min_momentum_pct}% | min_edge={self.min_edge_pct}%"
        )
        self._binance_task = asyncio.create_task(self._run_binance_ws())
        self.task = asyncio.create_task(self._run_polling())
        while self.running:
            await asyncio.sleep(1)

    async def stop(self):
        self.running = False
        for t in [self._binance_task, self.task]:
            if t:
                t.cancel()
                try:
                    await t
                except asyncio.CancelledError:
                    pass

    async def _run_binance_ws(self):
        import json

        ws_symbol = self._base_asset.lower() + "usdt"
        url = f"wss://stream.binance.com:9443/stream?streams={ws_symbol}@bookTicker"

        while self.running:
            try:
                import aiohttp

                async with aiohttp.ClientSession() as session:
                    async with session.ws_connect(url) as ws:
                        print(f"[Oracle Feeder] Binance WS conectado para {ws_symbol}")
                        async for msg in ws:
                            if not self.running:
                                break
                            data = json.loads(msg.data)
                            ticker = data.get("data", {})
                            if ticker:
                                bid = float(ticker.get("b", 0))
                                ask = float(ticker.get("B", 0))
                                price = (
                                    round((bid + ask) / 2, 4)
                                    if bid > 0 and ask > 0
                                    else bid or ask
                                )
                                if price > 0:
                                    self._binance_price = price
                                    self._price_history.append((time.time(), price))
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[Oracle Feeder] Binance WS error: {e}")
                await asyncio.sleep(5)

    def _calc_momentum(self):
        if len(self._price_history) < 2:
            return 0.0

        now = time.time()
        cutoff = now - self.momentum_window
        recent = [(t, p) for t, p in self._price_history if t >= cutoff]

        if len(recent) < 2:
            return 0.0

        oldest_price = recent[0][1]
        newest_price = recent[-1][1]

        if oldest_price <= 0:
            return 0.0

        return ((newest_price - oldest_price) / oldest_price) * 100

    async def _run_polling(self):
        from limitless_sdk.api import HttpClient

        http_client = HttpClient()

        try:
            while self.running:
                try:
                    await _scan_markets(http_client, self)
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    print(f"[Oracle Feeder] Scan error: {e}")
                await asyncio.sleep(self.poll_interval)
        finally:
            await http_client.close()


async def _scan_markets(http_client, feeder):
    from limitless_sdk.markets import MarketFetcher

    mf = MarketFetcher(http_client)
    resp = await mf.get_active_markets()
    markets = resp.data if hasattr(resp, "data") else []

    if feeder._binance_price <= 0:
        return

    pct_change = feeder._calc_momentum()
    abs_change = abs(pct_change)

    if abs_change < feeder.min_momentum_pct:
        return

    momentum_direction = 1 if pct_change > 0 else -1

    signals_emitted = 0

    for m in markets:
        if signals_emitted >= feeder._max_signals_per_scan:
            break

        slug = m.slug if hasattr(m, "slug") else ""
        title = m.title if hasattr(m, "title") else ""

        if "up-or-down" not in slug.lower():
            continue

        slug_lower = slug.lower()
        asset_match = False
        for keyword in SYMBOL_MAP.get(feeder._base_asset, []):
            if keyword in slug_lower:
                asset_match = True
                break
        if not asset_match:
            continue

        now = time.time()
        if slug in feeder._seen_markets:
            if now - feeder._seen_markets[slug] < feeder._cooldown:
                continue

        prices = m.prices if hasattr(m, "prices") else []
        if not prices or len(prices) < 2:
            continue

        yes_price = float(prices[0])
        no_price = float(prices[1])

        expires_at = 0
        if hasattr(m, "expiration_timestamp") and m.expiration_timestamp:
            expires_at = m.expiration_timestamp / 1000

        ttl = expires_at - now if expires_at > 0 else 9999
        if ttl < 30 or ttl > 3600:
            continue

        fair_yes = min(0.95, max(0.05, 0.50 + pct_change * 8))
        fair_no = min(0.95, max(0.05, 0.50 - pct_change * 8))

        signal = 0
        edge = 0.0
        chosen_price = 0.0
        chosen_side = ""

        if momentum_direction == 1 and yes_price < 0.50:
            edge = fair_yes - yes_price
            if edge >= feeder.min_edge_pct:
                signal = 1
                chosen_price = yes_price
                chosen_side = "YES"

        elif momentum_direction == -1 and no_price < 0.50:
            edge = fair_no - no_price
            if edge >= feeder.min_edge_pct:
                signal = -1
                chosen_price = no_price
                chosen_side = "NO"

        if signal != 0:
            feeder._seen_markets[slug] = now
            signals_emitted += 1

            direction = "UP" if signal == 1 else "DOWN"
            confidence = min(edge / 0.20, 1.0)

            print(
                f"[Oracle Signal] {title} | "
                f"{feeder._base_asset} momentum: {pct_change:+.3f}% ({direction}) | "
                f"{chosen_side}@{chosen_price:.4f} | "
                f"Fair: {fair_yes:.4f}/{fair_no:.4f} | "
                f"Edge: {edge:+.4f} ({edge * 100:.1f}%) | "
                f"Conf: {confidence:.2f} | "
                f"TTL: {ttl:.0f}s | "
                f"Price: ${feeder._binance_price:,.2f}"
            )

            event = PriceUpdateEvent(
                symbol=f"oracle_{slug}",
                price=chosen_price,
                ask=chosen_price,
                bid=chosen_price,
            )

            event._arb_data = {
                "type": "oracle_momentum",
                "signal": signal,
                "direction": direction,
                "side": chosen_side,
                "market_price": chosen_price,
                "yes_price": yes_price,
                "no_price": no_price,
                "fair_yes": fair_yes,
                "fair_no": fair_no,
                "edge": edge,
                "confidence": confidence,
                "pct_change": pct_change,
                "binance_price": feeder._binance_price,
                "title": title,
                "slug": slug,
                "expires_at": expires_at,
                "ttl": ttl,
            }

            await feeder.queue.put(event)
