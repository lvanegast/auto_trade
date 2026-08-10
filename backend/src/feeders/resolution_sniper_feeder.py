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


# Consecutive-scan confirmation: {event_id: count} — solo emitir tras N scans estables
_sniper_confirmations: dict = {}
_sniper_confirmations_seen: dict = {}  # última vez visto, para limpieza


class ResolutionSniperFeeder(BaseFeeder):
    def __init__(
        self,
        symbol: str,
        event_queue: asyncio.Queue,
        scope: str = "crypto",
    ):
        super().__init__(symbol.upper(), event_queue)
        # Alcance del feeder: "crypto" | "sports". Cada worker tiene SU PROPIO
        # feeder y escanea SOLO su categoría (Worker 7 = crypto, Worker 8 = sports).
        # No escanear las dos en la misma instancia: contamina las señales y el
        # tracking de resoluciones de un worker con la categoría del otro.
        self.scope = scope
        self.poll_interval = float(os.getenv("SNIPER_POLL_INTERVAL", "5.0"))
        # Rate-limit interno por instancia (cada worker escanea a su propio ritmo)
        self._last_scan_time = 0.0
        self._scan_lock = asyncio.Lock()
        # Umbral más alto: solo comprar lo casi-ya-resuelto. La EV es W - entry,
        # así que un entry de 0.975+ exige >97.5% de win real.
        self.min_entry_price = float(os.getenv("SNIPER_MIN_ENTRY_PRICE", "0.975"))
        self.max_entry_price = float(os.getenv("SNIPER_MAX_ENTRY_PRICE", "0.98"))
        # Finance (Gold, Meta, ETFs): menos volátil que crypto → rango más amplio
        # para entrar más temprano y capturar más oportunidades.
        self.finance_min_entry_price = float(os.getenv("SNIPER_FINANCE_MIN_ENTRY_PRICE", "0.95"))
        self.finance_max_entry_price = float(os.getenv("SNIPER_FINANCE_MAX_ENTRY_PRICE", "0.985"))
        # Solo snipear mercados con poca vida restante (el resultado ya está decidido)
        self.max_seconds_to_resolution = float(
            os.getenv("SNIPER_MAX_SECONDS_TO_RESOLUTION", "1800")
        )
        # Para deportes el partido puede tener horas de vida restante; la
        # "casi-certeza" (YES ~0.975-0.98) aparece en los minutos/horas finales.
        # Umbral separado y más holgado que el de crypto up/down.
        self.sports_max_seconds_to_resolution = float(
            os.getenv("SNIPER_SPORTS_MAX_SECONDS_TO_RESOLUTION", "14400")
        )
        # Confirmación: N scans consecutivos en rango antes de emitir señal
        self.min_consecutive_scans = int(
            os.getenv("SNIPER_MIN_CONSECUTIVE_SCANS", "3")
        )
        self.task = None

    @staticmethod
    def _parse_expiration(slug: str):
        """Extrae la expiración (unix) del slug up-or-down.

        El timestamp del slug es el INICIO de la ventana, no la expiración.
        La resolución ocurre start + duración según el patrón:
        ...-5-min-<ts> / ...-15-min-<ts> / ...-hourly-<ts> / ...-daily-<ts> / ...-weekly-<ts>
        """
        import re

        patterns = [
            (r"-(\d+)-min-(\d+)$", 60),
            (r"-(\d+)-hour-(\d+)$", 3600),
            (r"-hourly-(\d+)$", 3600),
            (r"-daily-(\d+)$", 86400),
            (r"-weekly-(\d+)$", 604800),
            (r"-(\d+)-day-(\d+)$", 86400),
        ]
        for pat, mult in patterns:
            m = re.search(pat, slug)
            if m:
                if len(m.groups()) == 2:
                    dur = int(m.group(1)) * mult
                    ts_val = int(m.group(2))
                else:
                    ts_val = int(m.group(1))
                    dur = mult
                ts_val = ts_val / 1000.0 if ts_val > 1000000000000 else float(ts_val)
                return ts_val + dur
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
            f"Scope: {self.scope} | "
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
        now = time.time()
        if now - self._last_scan_time < 5.0:
            return
        async with self._scan_lock:
            self._last_scan_time = now
            self._prune_confirmations()
            try:
                from src.engine.latency_tracker import latency_tracker

                # Lista de (market, category). category = "crypto" | "sports"
                # para enrutar la oportunidad a la sala correcta en edge_snapshots
                # y Telegram (TELEGRAM_CHAT_ID_CRYPTO vs TELEGRAM_CHAT_ID_SPORTS).
                scan_items = []

                if self.scope in ("crypto", "both"):
                    page_ids = [
                        "5e76699e-8763-4c91-85de-3efeb064efec",  # Crypto only
                    ]

                    for page_id in page_ids:
                        try:
                            async with latency_tracker.measure("resolution_sniper", "get_markets") as m:
                                resp = await self._page_fetcher.get_markets(page_id, {"limit": 50})
                                m.result = resp

                            page_m = resp.data if hasattr(resp, "data") else (resp.get("data", []) if isinstance(resp, dict) else [])
                            for mk in page_m:
                                scan_items.append((mk, "crypto"))
                        except Exception as pe:
                            if "TimeoutError" not in str(type(pe)) and "Cannot connect" not in str(pe):
                                print(f"[Resolution Sniper] Error fetching page {page_id}: {pe}")

                if self.scope in ("sports", "both"):
                    # Páginas deportivas (mismo patrón: YES casi-cerrado pre-resolución).
                    # Los mercados sports exponen expiration_timestamp (ms) como atributo
                    # del objeto, no como patrón del slug (a diferencia de crypto up/down).
                    for path in ["/sport", "/esports"]:
                        try:
                            page = await self._page_fetcher.get_market_page_by_path(path)
                            resp = await self._page_fetcher.get_markets(page.id, {"limit": 100})
                            page_m = resp.data if hasattr(resp, "data") else (resp.get("data", []) if isinstance(resp, dict) else [])
                            for mk in page_m:
                                scan_items.append((mk, "sports"))
                        except Exception as pe:
                            if "TimeoutError" not in str(type(pe)) and "Cannot connect" not in str(pe):
                                print(f"[Resolution Sniper] Error fetching sports page {path}: {pe}")

                    # Finance: Gold, Meta, NVIDIA, ETFs — menos volátil que crypto,
                    # rango más amplio [0.95, 0.985]. Mismo patrón up-or-down.
                    for path in ["/finance"]:
                        try:
                            page = await self._page_fetcher.get_market_page_by_path(path)
                            resp = await self._page_fetcher.get_markets(page.id, {"limit": 50})
                            page_m = resp.data if hasattr(resp, "data") else (resp.get("data", []) if isinstance(resp, dict) else [])
                            for mk in page_m:
                                scan_items.append((mk, "finance"))
                        except Exception as pe:
                            if "TimeoutError" not in str(type(pe)) and "Cannot connect" not in str(pe):
                                print(f"[Resolution Sniper] Error fetching finance page: {pe}")

                snipers_found = 0
                _diag = {"total": 0, "no_slug": 0, "non_crypto": 0, "non_sports": 0, "no_exp": 0, "exp_filtered": 0,
                         "price_out_of_range": 0, "no_liquidity": 0, "waiting_confirmation": 0}
                for m, category in scan_items:
                    slug = m.slug if hasattr(m, "slug") else (m.get("slug", "") if isinstance(m, dict) else "")
                    title = m.title if hasattr(m, "title") else (m.get("title", "") if isinstance(m, dict) else "")
                    _diag["total"] += 1
                    if not slug:
                        _diag["no_slug"] += 1
                        continue

                    if category == "crypto":
                        # FILTER: Only process crypto markets (limitless_crypto_ prefix)
                        # Skip sports markets
                        if "crypto" not in slug.lower() and "up-or-down" not in slug.lower():
                            self._reject(f"limitless_sniper_{slug}")
                            _diag["non_crypto"] += 1
                            continue
                        exp = self._parse_expiration(slug)
                        max_res_secs = self.max_seconds_to_resolution
                        _min_price = self.min_entry_price
                        _max_price = self.max_entry_price
                    elif category == "finance":
                        # Finance: mismo patrón up-or-down que crypto, pero rango
                        # más amplio [0.95, 0.985] por menor volatilidad.
                        # Ventana más amplia (4h) como sports — los mercados finance
                        # expiran menos frecuentemente que crypto (daily/weekly).
                        if "up-or-down" not in slug.lower():
                            self._reject(f"limitless_sniper_{slug}")
                            _diag["non_crypto"] += 1
                            continue
                        exp = self._parse_expiration(slug)
                        max_res_secs = self.sports_max_seconds_to_resolution
                        _min_price = self.finance_min_entry_price
                        _max_price = self.finance_max_entry_price
                    else:
                        # Sports markets must NOT be crypto up/down slugs
                        if "crypto" in slug.lower() or "up-or-down" in slug.lower():
                            self._reject(f"limitless_sniper_{slug}")
                            _diag["non_sports"] += 1
                            continue
                        # expiration_timestamp real (ms) del mercado deportivo
                        exp_ts = getattr(m, "expiration_timestamp", None) or (m.get("expiration_timestamp") if isinstance(m, dict) else None)
                        exp = (float(exp_ts) / 1000.0) if exp_ts else None
                        max_res_secs = self.sports_max_seconds_to_resolution
                        _min_price = self.min_entry_price
                        _max_price = self.max_entry_price

                    # FILTER: solo mercados cerca de resolver (el resultado ya está decidido)
                    remaining = -1
                    if exp is None:
                        _diag["no_exp"] += 1
                    else:
                        remaining = exp - now
                        if remaining < 0 or remaining > max_res_secs:
                            self._reject(f"limitless_sniper_{slug}")
                            _diag["exp_filtered"] += 1
                            continue

                    # Check for single/binary markets
                    from src.limitless_price_cache import async_get_limitless_executable_price

                    # Si el grupo tiene sub-mercados, NO procesar el slug principal
                    # (es solo el wrapper del grupo). Procesar sub-mercados abajo
                    # usando el slug del grupo como event_id para dedup de Telegram.
                    subs = getattr(m, "markets", None) or (m.get("markets") if isinstance(m, dict) else None)
                    _has_subs = subs and isinstance(subs, list) and len(subs) > 0

                    if not _has_subs:
                        book = await async_get_limitless_executable_price(slug)
                        if book:
                            yes_ask = book["yes_ask"]
                            yes_bid = book["yes_bid"]
                            no_ask = 1.0 - yes_bid
                            # Lado YES casi-seguro
                            if _min_price <= yes_ask <= _max_price and book["ask_size"] > 0:
                                event_id = f"limitless_sniper_{slug}"
                                if self._confirm(event_id):
                                    snipers_found += 1
                                    print(f"[Resolution Sniper] Found YES ({category}): {title[:50]} YES_ASK={yes_ask:.4f} remaining={remaining:.0f}s")
                                    await self._emit_sniper_signal(slug, title, yes_ask, side="YES", category=category)
                                else:
                                    _diag["waiting_confirmation"] += 1
                            # Lado NO casi-seguro (NO_ask = 1 - yes_bid)
                            elif _min_price <= no_ask <= _max_price and book["bid_size"] > 0:
                                event_id = f"limitless_sniper_{slug}"
                                if self._confirm(event_id):
                                    snipers_found += 1
                                    print(f"[Resolution Sniper] Found NO ({category}): {title[:50]} NO_ASK={no_ask:.4f} remaining={remaining:.0f}s")
                                    await self._emit_sniper_signal(slug, title, no_ask, side="NO", category=category)
                                else:
                                    _diag["waiting_confirmation"] += 1
                            else:
                                self._reject(f"limitless_sniper_{slug}")
                                _diag["price_out_of_range"] += 1
                        else:
                            _diag["no_liquidity"] += 1

                    # Check sub-markets in groups
                    if _has_subs:
                        # Solo procesar el PRIMER sub-mercado del grupo (moneyline).
                        # Los demás (sets, games, spread, total) son mercados
                        # independientes que por ahora NO se snipean.
                        # TODO: explorar sub-mercados como oportunidades adicionales.
                        sub = subs[0]
                        sub_slug = getattr(sub, "slug", "") if hasattr(sub, "slug") else (sub.get("slug", "") if isinstance(sub, dict) else "")
                        sub_title = getattr(sub, "title", "") if hasattr(sub, "title") else (sub.get("title", "") if isinstance(sub, dict) else "")
                        if not sub_slug:
                            self._reject(f"limitless_sniper_{sub_slug}")
                        else:
                            if category == "sports":
                                sub_exp_ts = getattr(sub, "expiration_timestamp", None) or (sub.get("expiration_timestamp") if isinstance(sub, dict) else None)
                                sub_exp = (float(sub_exp_ts) / 1000.0) if sub_exp_ts else exp
                            else:
                                sub_exp = self._parse_expiration(sub_slug)
                            sub_remaining = -1
                            if sub_exp is not None:
                                sub_remaining = sub_exp - now
                                if sub_remaining < 0 or sub_remaining > max_res_secs:
                                    self._reject(f"limitless_sniper_{sub_slug}")
                                    _diag["exp_filtered"] += 1
                                else:
                                    from src.limitless_price_cache import async_get_limitless_executable_price
                                    sub_book = await async_get_limitless_executable_price(sub_slug)
                                    if sub_book:
                                        sub_yes = sub_book["yes_ask"]
                                        sub_no = 1.0 - sub_book["yes_bid"]
                                        if _min_price <= sub_yes <= _max_price and sub_book["ask_size"] > 0:
                                            event_id = f"limitless_sniper_{sub_slug}"
                                            if self._confirm(event_id):
                                                snipers_found += 1
                                                print(f"[Resolution Sniper] Found YES ({category}): {sub_title[:50]} YES_ASK={sub_yes:.4f} remaining={sub_remaining:.0f}s")
                                                await self._emit_sniper_signal(sub_slug, sub_title, sub_yes, side="YES", category=category)
                                            else:
                                                _diag["waiting_confirmation"] += 1
                                        elif _min_price <= sub_no <= _max_price and sub_book["bid_size"] > 0:
                                            event_id = f"limitless_sniper_{sub_slug}"
                                            if self._confirm(event_id):
                                                snipers_found += 1
                                                print(f"[Resolution Sniper] Found NO ({category}): {sub_title[:50]} NO_ASK={sub_no:.4f} remaining={sub_remaining:.0f}s")
                                                await self._emit_sniper_signal(sub_slug, sub_title, sub_no, side="NO", category=category)
                                            else:
                                                _diag["waiting_confirmation"] += 1
                                        else:
                                            self._reject(f"limitless_sniper_{sub_slug}")
                                            _diag["price_out_of_range"] += 1
                                    else:
                                        _diag["no_liquidity"] += 1

                    # Delay between markets
                    await asyncio.sleep(0.1)

                print(f"[Resolution Sniper] Scan complete: {len(scan_items)} markets checked, {snipers_found} snipers found | diag={_diag}")

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

    async def _emit_sniper_signal(self, slug: str, title: str, entry_price: float, side: str = "YES", category: str = "crypto"):
        """Emit a PriceUpdateEvent for the strategy to process."""
        from src.strategy.resolution_sniper import update_sniper_data

        event_id = f"limitless_sniper_{slug}"

        # Update strategy data
        update_sniper_data(
            event_id=event_id,
            yes_price=entry_price,
            title=title,
            slug=slug,
            sport=category,
            side=side,
            category=category,
        )

        # Create and emit price event
        event = PriceUpdateEvent(
            symbol=event_id,
            price=entry_price,
            ask=entry_price,
            bid=entry_price,
        )
        await self.queue.put(event)
