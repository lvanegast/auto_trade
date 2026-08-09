"""
Resolution Sniper Feeder — Monitors Limitless sports markets for near-certain outcomes.

Scans markets where YES price > 0.975 (97.5%+ probability).
These are markets where one outcome is almost guaranteed.
Strategy: Buy YES at 97.5-98¢, hold until resolution, receive $1.00.
"""

import asyncio
import os
import time
from src.feeders.base import BaseFeeder
from src.events import PriceUpdateEvent


# Shared cache to prevent rate limiting
_last_sniper_scan_time = 0.0
_sniper_scan_lock = asyncio.Lock()
# Consecutive-scan confirmation: {event_id: count} — solo emitir tras N scans estables
_sniper_confirmations: dict = {}
_sniper_confirmations_seen: dict = {}  # última vez visto, para limpieza


class ResolutionSniperFeeder(BaseFeeder):
    def __init__(self, symbol: str, event_queue: asyncio.Queue):
        super().__init__(symbol.upper(), event_queue)
        self.poll_interval = float(os.getenv("SNIPER_POLL_INTERVAL", "5.0"))
        # Umbral más alto: solo comprar lo casi-ya-resuelto. La EV es W - entry,
        # así que un entry de 0.985+ exige >98.5% de win real.
        self.min_entry_price = float(os.getenv("SNIPER_MIN_ENTRY_PRICE", "0.985"))
        self.max_entry_price = float(os.getenv("SNIPER_MAX_ENTRY_PRICE", "0.995"))
        # Solo snipear mercados con poca vida restante (el resultado ya está decidido)
        self.max_seconds_to_resolution = float(
            os.getenv("SNIPER_MAX_SECONDS_TO_RESOLUTION", "1800")
        )
        # Confirmación: N scans consecutivos en rango antes de emitir señal
        self.min_consecutive_scans = int(
            os.getenv("SNIPER_MIN_CONSECUTIVE_SCANS", "3")
        )
        self.task = None

    @staticmethod
    def _parse_expiration(slug: str):
        """Extrae la expiración (unix) del slug. Ej: ...weekly-1785729600"""
        parts = slug.split("-")
        ts_str = parts[-1]
        if not ts_str.isdigit():
            return None
        ts_val = int(ts_str)
        return ts_val / 1000.0 if ts_val > 1000000000000 else float(ts_val)

    def _confirm(self, event_id: str) -> bool:
        """Incrementa el contador de scans consecutivos; True cuando alcanza el mínimo."""
        now = time.time()
        if event_id not in _sniper_confirmations:
            _sniper_confirmations[event_id] = 0
        _sniper_confirmations[event_id] += 1
        _sniper_confirmations_seen[event_id] = now
        return _sniper_confirmations[event_id] >= self.min_consecutive_scans

    def _reject(self, event_id: str):
        """Resetea la confirmación (precio salió del rango o sin liquidez)."""
        _sniper_confirmations.pop(event_id, None)

    @staticmethod
    def _prune_confirmations(max_age: float = 120.0):
        """Limpia confirmaciones viejas para no acumular memoria."""
        now = time.time()
        for k in list(_sniper_confirmations_seen):
            if now - _sniper_confirmations_seen.get(k, 0) > max_age:
                _sniper_confirmations.pop(k, None)
                _sniper_confirmations_seen.pop(k, None)

    async def start(self):
        self.running = True
        print(
            f"[Feeder Resolution Sniper] Iniciando polling cada {self.poll_interval}s | "
            f"Rango: {self.min_entry_price:.2f} - {self.max_entry_price:.2f} | "
            f"Vida restante máx: {self.max_seconds_to_resolution/60:.0f}min | "
            f"Confirmación: {self.min_consecutive_scans} scans"
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
            self._prune_confirmations()
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
                        self._reject(f"limitless_sniper_{slug}")
                        continue

                    # FILTER: solo mercados cerca de resolver (el resultado ya está decidido)
                    exp = self._parse_expiration(slug)
                    if exp is not None:
                        remaining = exp - now
                        if remaining < 0 or remaining > self.max_seconds_to_resolution:
                            self._reject(f"limitless_sniper_{slug}")
                            continue

                    # Check for single/binary markets
                    from src.limitless_price_cache import async_get_limitless_executable_price
                    book = await async_get_limitless_executable_price(slug)
                    if book:
                        yes_ask = book["yes_ask"]
                        yes_bid = book["yes_bid"]
                        no_ask = 1.0 - yes_bid
                        # Lado YES casi-seguro
                        if self.min_entry_price <= yes_ask <= self.max_entry_price and book["ask_size"] > 0:
                            event_id = f"limitless_sniper_{slug}"
                            if self._confirm(event_id):
                                snipers_found += 1
                                print(f"[Resolution Sniper] Found YES: {title[:50]} YES_ASK={yes_ask:.4f} remaining={remaining:.0f}s")
                                await self._emit_sniper_signal(slug, title, yes_ask, side="YES")
                        # Lado NO casi-seguro (NO_ask = 1 - yes_bid)
                        elif self.min_entry_price <= no_ask <= self.max_entry_price and book["bid_size"] > 0:
                            event_id = f"limitless_sniper_{slug}"
                            if self._confirm(event_id):
                                snipers_found += 1
                                print(f"[Resolution Sniper] Found NO: {title[:50]} NO_ASK={no_ask:.4f} remaining={remaining:.0f}s")
                                await self._emit_sniper_signal(slug, title, no_ask, side="NO")
                        else:
                            self._reject(f"limitless_sniper_{slug}")

                    # Check sub-markets in groups
                    subs = getattr(m, "markets", None) or (m.get("markets") if isinstance(m, dict) else None)
                    if subs and isinstance(subs, list):
                        for sub in subs:
                            sub_slug = getattr(sub, "slug", "") if hasattr(sub, "slug") else (sub.get("slug", "") if isinstance(sub, dict) else "")
                            sub_title = getattr(sub, "title", "") if hasattr(sub, "title") else (sub.get("title", "") if isinstance(sub, dict) else "")
                            sub_prices = getattr(sub, "prices", None) if hasattr(sub, "prices") else (sub.get("prices") if isinstance(sub, dict) else None)
                            if not sub_slug:
                                self._reject(f"limitless_sniper_{sub_slug}")
                                continue
                            sub_exp = self._parse_expiration(sub_slug)
                            if sub_exp is not None:
                                sub_remaining = sub_exp - now
                                if sub_remaining < 0 or sub_remaining > self.max_seconds_to_resolution:
                                    self._reject(f"limitless_sniper_{sub_slug}")
                                    continue

                            from src.limitless_price_cache import async_get_limitless_executable_price
                            sub_book = await async_get_limitless_executable_price(sub_slug)
                            if sub_book:
                                sub_yes = sub_book["yes_ask"]
                                sub_no = 1.0 - sub_book["yes_bid"]
                                if self.min_entry_price <= sub_yes <= self.max_entry_price and sub_book["ask_size"] > 0:
                                    event_id = f"limitless_sniper_{sub_slug}"
                                    if self._confirm(event_id):
                                        snipers_found += 1
                                        print(f"[Resolution Sniper] Found YES: {sub_title[:50]} YES_ASK={sub_yes:.4f} remaining={sub_remaining:.0f}s")
                                        await self._emit_sniper_signal(sub_slug, sub_title, sub_yes, side="YES")
                                elif self.min_entry_price <= sub_no <= self.max_entry_price and sub_book["bid_size"] > 0:
                                    event_id = f"limitless_sniper_{sub_slug}"
                                    if self._confirm(event_id):
                                        snipers_found += 1
                                        print(f"[Resolution Sniper] Found NO: {sub_title[:50]} NO_ASK={sub_no:.4f} remaining={sub_remaining:.0f}s")
                                        await self._emit_sniper_signal(sub_slug, sub_title, sub_no, side="NO")
                                else:
                                    self._reject(f"limitless_sniper_{sub_slug}")

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

    async def _emit_sniper_signal(self, slug: str, title: str, entry_price: float, side: str = "YES"):
        """Emit a PriceUpdateEvent for the strategy to process."""
        from src.strategy.resolution_sniper import update_sniper_data

        event_id = f"limitless_sniper_{slug}"

        # Update strategy data
        update_sniper_data(
            event_id=event_id,
            yes_price=entry_price,
            title=title,
            slug=slug,
            sport="crypto",
            side=side,
        )

        # Create and emit price event
        event = PriceUpdateEvent(
            symbol=event_id,
            price=entry_price,
            ask=entry_price,
            bid=entry_price,
        )
        await self.queue.put(event)
