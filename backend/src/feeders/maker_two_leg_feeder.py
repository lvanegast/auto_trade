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


# Shared cache to prevent rate limiting across workers
_last_maker_scan_time = 0.0
_maker_scan_lock = asyncio.Lock()
_cached_maker_events = []


class MakerTwoLegFeeder(BaseFeeder):
    def __init__(self, symbol: str, event_queue: asyncio.Queue):
        super().__init__(symbol.upper(), event_queue)
        self.poll_interval = float(os.getenv("MAKER_POLL_INTERVAL", "5.0"))
        self.page_ids = [
            "5e76699e-8763-4c91-85de-3efeb064efec",  # Crypto only
        ]
        self.task = None
        self._last_instance_scan = 0.0

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
        self._http_client = http_client
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
        global _last_maker_scan_time, _cached_maker_events
        now = time.time()
        if now - self._last_instance_scan < self.poll_interval:
            return
        self._last_instance_scan = now

        # Si otro worker (ej. worker_1) ya escaneó hace <5s, reusar los eventos cacheados
        if now - _last_maker_scan_time < 5.0 and _cached_maker_events:
            for ev in _cached_maker_events:
                await self.queue.put(ev)
            return

        async with _maker_scan_lock:
            # Doble comprobación tras entrar al lock
            if now - _last_maker_scan_time < 5.0 and _cached_maker_events:
                for ev in _cached_maker_events:
                    await self.queue.put(ev)
                return
            _last_maker_scan_time = now
            new_events = []
            try:
                from src.engine.latency_tracker import latency_tracker
                from src.utils.limitless_api_helper import fetch_markets_safe

                markets = []
                for page_id in self.page_ids:
                    try:
                        async with latency_tracker.measure("maker_two_leg", "get_markets"):
                            page_m = await fetch_markets_safe(self._http_client, page_id, limit=50)
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

                    # STRICT FILTER: Permitir EXCLUSIVAMENTE contratos intradía de 15 minutos y 1 hora.
                    # Prohibir mercados ultra-rápidos (5m), diarios (daily/24h) y semanales (weekly).
                    slug_lower = slug.lower()
                    if (
                        "-5-min-" in slug_lower or "-5min-" in slug_lower or
                        "-weekly-" in slug_lower or "-weekly" in slug_lower or
                        "-daily-" in slug_lower or "-daily" in slug_lower
                    ):
                        continue
                    is_intraday = any(x in slug_lower for x in ["-15-min-", "-15min-", "-hourly-", "-hourly", "-1-hour-", "-1h-"])
                    if not is_intraday:
                        continue

                    scanned += 1

                    # Volumen real transado (USD) — el indicador de "vivo".
                    # Soporta formato camelCase de API (volumeFormatted) o micro-USDC (volume / 1e6)
                    volume_raw = (
                        getattr(m, "volume_formatted", None)
                        or getattr(m, "volumeFormatted", None)
                        or (m.get("volumeFormatted") if isinstance(m, dict) else None)
                        or (m.get("volume_formatted") if isinstance(m, dict) else None)
                    )
                    try:
                        market_volume = float(volume_raw) if volume_raw is not None else 0.0
                    except (TypeError, ValueError):
                        market_volume = 0.0

                    if market_volume == 0.0 and isinstance(m, dict) and m.get("volume"):
                        try:
                            market_volume = float(m.get("volume")) / 1e6
                        except (TypeError, ValueError):
                            pass

                    # Expiración: calcular antes de consultar el orderbook para no gastar llamadas en mercados muertos
                    exp_raw = (
                        getattr(m, "expirationTimestamp", None)
                        or getattr(m, "expiration_timestamp", None)
                        or (m.get("expirationTimestamp") if isinstance(m, dict) else None)
                        or (m.get("expiration_timestamp") if isinstance(m, dict) else None)
                        or (m.get("endDate") if isinstance(m, dict) else None)
                    )
                    exp_ts = None
                    if exp_raw:
                        try:
                            val = float(exp_raw)
                            exp_ts = val / 1000.0 if val > 1e12 else val
                        except (ValueError, TypeError):
                            pass
                    if not exp_ts:
                        from src.feeders.resolution_sniper_feeder import ResolutionSniperFeeder
                        exp_ts = ResolutionSniperFeeder._parse_expiration(slug)

                    # Excluir mercados ya expirados o a menos de 120s de expirar
                    if exp_ts and (exp_ts - time.time() < 120.0):
                        continue

                    # Book real ejecutable (el spread ES nuestro edge de arbitraje, nunca bloquear spreads > 3.5%)
                    from src.limitless_price_cache import async_get_limitless_executable_price
                    book = await async_get_limitless_executable_price(slug, validate_maker_spread=False)
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
                    event.expiration_timestamp = exp_ts

                    await self.queue.put(event)
                    new_events.append(event)

                    # Delay entre markets para no saturar la API
                    await asyncio.sleep(0.05)

                _cached_maker_events = new_events
                print(f"[Maker 2-Leg] Scan completo: {len(markets)} markets, {scanned} crypto, "
                      f"books emitidos OK ({len(new_events)} eventos cacheados)")
                now_t = time.time()
                if not hasattr(self, "_last_db_log_time") or (now_t - self._last_db_log_time > 900):
                    self._last_db_log_time = now_t
                    try:
                        from src.api.app import db
                        db.log("INFO", f"[Maker 2-Leg Feeder] Scan completo: {len(markets)} mercados consultados, {scanned} crypto procesados", "worker_6")
                    except Exception:
                        pass

            except Exception as e:
                print(f"[Maker 2-Leg] Error scanning: {e}")
