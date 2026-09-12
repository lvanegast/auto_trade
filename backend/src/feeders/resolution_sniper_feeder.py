"""
Resolution Sniper Feeder — Monitors Limitless sports markets for near-certain outcomes.

Scans markets where YES price > 0.975 (97.5%+ probability).
These are markets where one outcome is almost guaranteed.
Strategy: Buy YES at 97.5-98¢, hold until resolution, receive $1.00.
"""

import asyncio
import os
import re
import time
from src.feeders.base import BaseFeeder
from src.events import PriceUpdateEvent


def _asset_key(title: str) -> str:
    """
    Slug corto a partir del título (ej. "ETH" -> "eth"). El slug real de
    Limitless para mercados up/down de N minutos codifica solo la ventana
    temporal (ej. "...-5-min-1786741200"), NO el activo — dos activos
    distintos que abren ventana en el mismo instante comparten ese slug.
    Se antepone el activo al event_id para no colisionar.
    """
    key = (title or "").strip().lower()
    key = re.sub(r"[^a-z0-9]+", "-", key).strip("-")
    return key or "unknown"


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
        # Confirmación de scans consecutivos: por INSTANCIA (antes eran dicts a
        # nivel de módulo, compartidos entre el feeder de worker 7 y el de worker 8,
        # pese a que el diseño asume aislamiento total por scope).
        self._sniper_confirmations: dict = {}
        self._sniper_confirmations_seen: dict = {}
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
        if event_id not in self._sniper_confirmations:
            self._sniper_confirmations[event_id] = 0
        self._sniper_confirmations[event_id] += 1
        self._sniper_confirmations_seen[event_id] = now
        return self._sniper_confirmations[event_id] >= self.min_consecutive_scans

    def _reject(self, event_id: str):
        """Resetea la confirmación (precio salió del rango o sin liquidez)."""
        self._sniper_confirmations.pop(event_id, None)

    def _prune_confirmations(self, max_age: float = 120.0):
        """Limpia confirmaciones viejas para no acumular memoria."""
        now = time.time()
        for k in list(self._sniper_confirmations_seen):
            if now - self._sniper_confirmations_seen.get(k, 0) > max_age:
                self._sniper_confirmations.pop(k, None)
                self._sniper_confirmations_seen.pop(k, None)

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
        self._http_client = http_client
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
                from src.utils.limitless_api_helper import fetch_markets_safe, get_page_id_safe

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
                            async with latency_tracker.measure("resolution_sniper", "get_markets"):
                                page_m = await fetch_markets_safe(self._http_client, page_id, limit=50)
                            for mk in page_m:
                                scan_items.append((mk, "crypto"))
                        except Exception as pe:
                            if "TimeoutError" not in str(type(pe)) and "Cannot connect" not in str(pe):
                                print(f"[Resolution Sniper] Error fetching page {page_id}: {pe}")

                if self.scope in ("sports", "both"):
                    # Páginas deportivas exclusivas (Fútbol, Tenis, Esports).
                    for path in ["/sport", "/esports"]:
                        try:
                            page_id = await get_page_id_safe(self._http_client, path)
                            if page_id:
                                page_m = await fetch_markets_safe(self._http_client, page_id, limit=100)
                                for mk in page_m:
                                    scan_items.append((mk, "sports"))
                        except Exception as pe:
                            if "TimeoutError" not in str(type(pe)) and "Cannot connect" not in str(pe):
                                print(f"[Resolution Sniper] Error fetching sports page {path}: {pe}")

                if self.scope in ("finance", "both"):
                    # Finance: Wall Street Equities (TSLA, NVDA, AAPL, SPY, etc.) y Gold
                    for path in ["/finance"]:
                        try:
                            page_id = await get_page_id_safe(self._http_client, path)
                            if page_id:
                                page_m = await fetch_markets_safe(self._http_client, page_id, limit=50)
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
                        # Finance: Wall Street Equities / Commodities.
                        # Ventana ultra-corta (máx 300s = 5 min antes del cierre de las 4:00 PM EDT)
                        # para evitar volatilidad de Power Hour y subasta de cierre (MOC).
                        if "up-or-down" not in slug.lower():
                            self._reject(f"limitless_sniper_{slug}")
                            _diag["non_crypto"] += 1
                            continue
                        exp = self._parse_expiration(slug)
                        max_res_secs = 300.0  # Máximo 5 minutos antes de la campana
                        _min_price = self.min_entry_price
                        _max_price = self.max_entry_price
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

                    # Check for single/binary markets
                    from src.limitless_price_cache import async_get_limitless_executable_price
                    from src.engine.spot_oracle_guard import SpotOracleGuard

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

                            target_side = None
                            entry_price = None
                            depth = 0
                            if _min_price <= yes_ask <= _max_price and book["ask_size"] > 0:
                                target_side = "YES"
                                entry_price = yes_ask
                                depth = book["ask_size"]
                            elif _min_price <= no_ask <= _max_price and book["bid_size"] > 0:
                                target_side = "NO"
                                entry_price = no_ask
                                depth = book["bid_size"]

                            if target_side:
                                # Validación Oracular de Seguridad (Z-Score y Spot Distance)
                                is_safe = True
                                safety_reason = "OK"
                                if category == "crypto":
                                    asset, strike = SpotOracleGuard.extract_market_info(m)
                                    if strike is None or asset == "UNKNOWN":
                                        is_safe = False
                                        safety_reason = f"No se pudo verificar strike ({strike}) o activo ({asset})"
                                    else:
                                        spot = SpotOracleGuard.get_spot_price(asset)
                                        if spot is None or spot <= 0:
                                            is_safe = False
                                            safety_reason = f"Sin cotización spot de Binance para {asset}"
                                        else:
                                            is_safe, z, delta_pct, safety_reason = SpotOracleGuard.evaluate_safety(
                                                asset=asset,
                                                spot_price=spot,
                                                strike_price=strike,
                                                side=target_side,
                                                remaining_seconds=remaining,
                                            )

                                elif category == "sports":
                                    # En deportes, la casi-certeza solo es válida cerca de la resolución final
                                    if remaining > 1800:
                                        is_safe = False
                                        safety_reason = f"Tiempo restante excesivo para certeza deportiva ({remaining:.0f}s > 1800s)"

                                elif category == "finance":
                                    # Para finanzas / acciones de Wall Street (Opción B: Equities Oracle Guard)
                                    if depth < 10.0:
                                        is_safe = False
                                        safety_reason = f"Liquidez insuficiente en libro ({depth:.1f} < $10 USD)"
                                    else:
                                        asset, strike = SpotOracleGuard.extract_market_info(m)
                                        if strike is None or asset == "UNKNOWN":
                                            is_safe = False
                                            safety_reason = f"No se pudo verificar strike ({strike}) o activo ({asset})"
                                        else:
                                            spot = SpotOracleGuard.get_spot_price(asset)
                                            if spot is None or spot <= 0:
                                                is_safe = False
                                                safety_reason = f"Sin cotización spot (Yahoo/Binance) para {asset}"
                                            else:
                                                is_safe, z, delta_pct, safety_reason = SpotOracleGuard.evaluate_safety(
                                                    asset=asset,
                                                    spot_price=spot,
                                                    strike_price=strike,
                                                    side=target_side,
                                                    remaining_seconds=remaining,
                                                    category="finance",
                                                )

                                if not is_safe:
                                    self._reject(f"limitless_sniper_{slug}")
                                    _diag["adverse_selection_blocked"] = _diag.get("adverse_selection_blocked", 0) + 1
                                    if _diag.get("adverse_selection_blocked", 0) <= 5:
                                        print(f"[Resolution Sniper BLOCKED] {title[:40]} {target_side}@{entry_price:.4f}: {safety_reason}")
                                else:
                                    event_id = f"limitless_sniper_{_asset_key(title)}_{slug}"
                                    if self._confirm(event_id):
                                        snipers_found += 1
                                        print(f"[Resolution Sniper] Found {target_side} ({category}): {title[:50]} ASK={entry_price:.4f} remaining={remaining:.0f}s | {safety_reason}")
                                        await self._emit_sniper_signal(slug, title, entry_price, side=target_side, category=category)
                                    else:
                                        _diag["waiting_confirmation"] += 1
                            else:
                                self._reject(f"limitless_sniper_{slug}")
                                _diag["price_out_of_range"] += 1
                        else:
                            _diag["no_liquidity"] += 1

                    # Check sub-markets in groups
                    if _has_subs:
                        # Evaluar todos los sub-mercados del grupo (moneyline, sets, games, spread, total)
                        for sub in subs:
                            sub_slug = getattr(sub, "slug", "") if hasattr(sub, "slug") else (sub.get("slug", "") if isinstance(sub, dict) else "")
                            sub_title = getattr(sub, "title", "") if hasattr(sub, "title") else (sub.get("title", "") if isinstance(sub, dict) else "")
                            if not sub_slug:
                                continue
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
                                    continue

                            from src.limitless_price_cache import async_get_limitless_executable_price
                            sub_book = await async_get_limitless_executable_price(sub_slug)
                            if sub_book:
                                sub_yes = sub_book["yes_ask"]
                                sub_no = 1.0 - sub_book["yes_bid"]
                                sub_target_side = None
                                sub_entry_price = None
                                if _min_price <= sub_yes <= _max_price and sub_book["ask_size"] > 0:
                                    sub_target_side = "YES"
                                    sub_entry_price = sub_yes
                                elif _min_price <= sub_no <= _max_price and sub_book["bid_size"] > 0:
                                    sub_target_side = "NO"
                                    sub_entry_price = sub_no

                                if sub_target_side:
                                    # Validación de seguridad para submercados
                                    sub_safe = True
                                    sub_safety_reason = "OK"
                                    if category == "crypto":
                                        sub_asset, sub_strike = SpotOracleGuard.extract_market_info(sub)
                                        if sub_strike is None or sub_asset == "UNKNOWN":
                                            sub_safe = False
                                            sub_safety_reason = f"No se pudo verificar strike ({sub_strike}) o activo ({sub_asset})"
                                        else:
                                            sub_spot = SpotOracleGuard.get_spot_price(sub_asset)
                                            if sub_spot is None or sub_spot <= 0:
                                                sub_safe = False
                                                sub_safety_reason = f"Sin spot Binance para {sub_asset}"
                                            else:
                                                sub_safe, z, delta_pct, sub_safety_reason = SpotOracleGuard.evaluate_safety(
                                                    asset=sub_asset,
                                                    spot_price=sub_spot,
                                                    strike_price=sub_strike,
                                                    side=sub_target_side,
                                                    remaining_seconds=sub_remaining,
                                                )
                                    elif category == "sports" and sub_remaining > 1800:
                                        sub_safe = False
                                        sub_safety_reason = f"Tiempo restante excesivo ({sub_remaining:.0f}s > 1800s)"
                                    elif category == "finance":
                                        if sub_depth < 10.0:
                                            sub_safe = False
                                            sub_safety_reason = f"Liquidez insuficiente ({sub_depth:.1f} < $10 USD)"
                                        else:
                                            sub_asset, sub_strike = SpotOracleGuard.extract_market_info(sub)
                                            if sub_strike is None or sub_asset == "UNKNOWN":
                                                sub_safe = False
                                                sub_safety_reason = f"No se pudo verificar strike ({sub_strike}) o activo ({sub_asset})"
                                            else:
                                                sub_spot = SpotOracleGuard.get_spot_price(sub_asset)
                                                if sub_spot is None or sub_spot <= 0:
                                                    sub_safe = False
                                                    sub_safety_reason = f"Sin spot (Yahoo/Binance) para {sub_asset}"
                                                else:
                                                    sub_safe, z, delta_pct, sub_safety_reason = SpotOracleGuard.evaluate_safety(
                                                        asset=sub_asset,
                                                        spot_price=sub_spot,
                                                        strike_price=sub_strike,
                                                        side=sub_target_side,
                                                        remaining_seconds=sub_remaining,
                                                        category="finance",
                                                    )

                                    if not sub_safe:
                                        self._reject(f"limitless_sniper_{sub_slug}")
                                        _diag["adverse_selection_blocked"] = _diag.get("adverse_selection_blocked", 0) + 1
                                    else:
                                        event_id = f"limitless_sniper_{_asset_key(sub_title)}_{sub_slug}"
                                        if self._confirm(event_id):
                                            snipers_found += 1
                                            print(f"[Resolution Sniper] Found {sub_target_side} ({category}): {sub_title[:50]} ASK={sub_entry_price:.4f} remaining={sub_remaining:.0f}s | {sub_safety_reason}")
                                            await self._emit_sniper_signal(sub_slug, sub_title, sub_entry_price, side=sub_target_side, category=category)
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
                now_t = time.time()
                if not hasattr(self, "_last_db_log_time") or (now_t - self._last_db_log_time > 900):
                    self._last_db_log_time = now_t
                    try:
                        from src.api.app import db
                        worker_id = "worker_7" if self.scope == "crypto" else ("worker_8" if self.scope == "sports" else "worker_9")
                        db.log(
                            "INFO",
                            f"[Resolution Sniper {self.scope.upper()}] Scan: {len(scan_items)} mercados, {snipers_found} en rango | exp_filtrados={_diag.get('exp_filtered',0)}, precio_fuera={_diag.get('price_out_of_range',0)}, oraculo_bloqueo={_diag.get('adverse_selection_blocked',0)}",
                            worker_id
                        )
                    except Exception:
                        pass

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

        event_id = f"limitless_sniper_{_asset_key(title)}_{slug}"

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
