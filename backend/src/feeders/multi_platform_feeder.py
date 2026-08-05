"""
MultiPlatformFeeder — Conecta a Limitless, Polymarket y Kalshi simultáneamente.

Un solo feeder que alimenta cross_platform_tracker con precios de 3 plataformas.
Optimizado para bajo uso de CPU: 3 conexiones en un solo worker.
"""

import asyncio
import os
import time
from src.feeders.base import BaseFeeder
from src.events import PriceUpdateEvent
from src.limitless_price_cache import async_get_limitless_executable_price


class MultiPlatformFeeder(BaseFeeder):
    """
    Feeder que conecta a múltiples plataformas de prediction markets.
    Alimenta cross_platform_tracker con precios en tiempo real.
    """

    def __init__(self, symbol: str, event_queue: asyncio.Queue):
        super().__init__(symbol.upper(), event_queue)
        self.poll_interval = float(os.getenv("MULTI_PLATFORM_POLL_INTERVAL", "15.0"))
        self.task = None

        # Estado de conexiones
        self._limitless_connected = False
        self._polymarket_connected = False
        self._kalshi_connected = False

        # Importar tracker aquí para asegurar que usamos la misma instancia
        from src.strategy.cross_platform_tracker import cross_platform_tracker
        self._tracker = cross_platform_tracker

    async def start(self):
        self.running = True
        print("[MultiPlatform] Iniciando conexiones a Limitless, Polymarket y Kalshi...")
        self.task = asyncio.create_task(self._run_all_connections())
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

    async def _run_all_connections(self):
        """Ejecuta las 3 conexiones en paralelo."""
        try:
            await asyncio.gather(
                self._run_limitless(),
                self._run_polymarket(),
                self._run_kalshi(),
                return_exceptions=True,
            )
        except Exception as e:
            print(f"[MultiPlatform] Error general: {e}")

    # ============================================================
    # LIMITLESS
    # ============================================================
    async def _run_limitless(self):
        """Conecta a Limitless Sports y alimenta el tracker."""
        from limitless_sdk.api import HttpClient
        from limitless_sdk.market_pages import MarketPageFetcher

        http_client = HttpClient()
        page_fetcher = MarketPageFetcher(http_client)

        print("[MultiPlatform-Limitless] Conectado a Limitless Sports")
        self._limitless_connected = True

        try:
            while self.running:
                try:
                    await self._scan_limitless_markets(page_fetcher)
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    print(f"[MultiPlatform-Limitless] Error: {e}")
                await asyncio.sleep(self.poll_interval)
        finally:
            await http_client.close()
            self._limitless_connected = False

    async def _scan_limitless_markets(self, page_fetcher):
        """Escanea mercados de Limitless y actualiza el tracker."""
        from src.engine.latency_tracker import latency_tracker

        page_ids = [
            "2a91349c-3308-4234-afb7-0663e42968c1",  # Sport
            "f2a04a4e-580a-4cd1-bcc9-c23ed9ff8916",  # Esports
        ]

        markets = []
        for page_id in page_ids:
            try:
                async with latency_tracker.measure("limitless_multi", "get_markets") as m:
                    resp = await page_fetcher.get_markets(page_id, {"limit": 30})
                    m.result = resp

                page_m = resp.data if hasattr(resp, "data") else (resp.get("data", []) if isinstance(resp, dict) else [])
                markets.extend(page_m)
            except asyncio.CancelledError:
                raise
            except Exception as pe:
                if "TimeoutError" not in str(type(pe)) and "Cannot connect" not in str(pe):
                    print(f"[MultiPlatform-Limitless] Error fetching page {page_id}: {type(pe).__name__}: {pe}")

        if markets:
            print(f"[MultiPlatform-Limitless] Fetched {len(markets)} markets")

        ll_updated = 0
        for m in markets:
            slug = m.slug if hasattr(m, "slug") else (m.get("slug", "") if isinstance(m, dict) else "")
            title = m.title if hasattr(m, "title") else (m.get("title", "") if isinstance(m, dict) else "")
            if not slug:
                continue

            # Sub-markets (grupos)
            subs = getattr(m, "markets", None) or (m.get("markets") if isinstance(m, dict) else None)
            if subs and isinstance(subs, list) and len(subs) >= 2:
                for sub in subs:
                    sub_slug = getattr(sub, "slug", "") or (sub.get("slug", "") if isinstance(sub, dict) else "")
                    sub_title = getattr(sub, "title", "") or (sub.get("title", "") if isinstance(sub, dict) else "")
                    prices = getattr(sub, "prices", None) or (sub.get("prices") if isinstance(sub, dict) else None)

                    if prices and len(prices) >= 1:
                        try:
                            book = await async_get_limitless_executable_price(sub_slug)
                            if not book:
                                continue
                            # Usar nombre normalizado como event_id para emparejar con Kalshi
                            normalized_title = self._normalize_match_name(title)
                            outcome_id = self._normalize_match_name(sub_title)
                            event_id = f"match_{normalized_title}__{outcome_id}"
                            self._tracker.update_book(
                                event_id=event_id,
                                platform="limitless",
                                yes_bid=book["yes_bid"],
                                yes_ask=book["yes_ask"],
                                bid_depth=book["bid_size"],
                                ask_depth=book["ask_size"],
                            )
                            # Debug: print first few updates
                            if not hasattr(self, '_limitless_debug_count'):
                                self._limitless_debug_count = 0
                            if self._limitless_debug_count < 10:
                                print(f"[MultiPlatform-Limitless] DEBUG: Updated {event_id} ask={book['yes_ask']}")
                                self._limitless_debug_count += 1
                            ll_updated += 1
                        except (ValueError, TypeError):
                            pass

            # Mercado individual
            prices = getattr(m, "prices", None) or (m.get("prices") if isinstance(m, dict) else None)
            if prices and len(prices) >= 2:
                try:
                    book = await async_get_limitless_executable_price(slug)
                    if not book:
                        continue
                    normalized_title = self._normalize_match_name(title)
                    event_id = f"match_{normalized_title}__yes"
                    self._tracker.update_book(
                        event_id=event_id,
                        platform="limitless",
                        yes_bid=book["yes_bid"],
                        yes_ask=book["yes_ask"],
                        bid_depth=book["bid_size"],
                        ask_depth=book["ask_size"],
                    )
                    if not hasattr(self, '_limitless_debug_count'):
                        self._limitless_debug_count = 0
                    if self._limitless_debug_count < 10:
                        print(f"[MultiPlatform-Limitless] DEBUG: Updated {event_id} ask={book['yes_ask']}")
                        self._limitless_debug_count += 1
                    ll_updated += 1
                except (ValueError, TypeError):
                    pass

        if ll_updated > 0:
            print(f"[MultiPlatform-Limitless] Updated {ll_updated} markets in tracker")

    def _normalize_match_name(self, title: str) -> str:
        """Normaliza nombre de match para emparejar Limitless y Kalshi."""
        import re
        # Convertir a minúsculas, quitar puntos, comas
        normalized = title.lower().strip()
        normalized = normalized.replace(".", "").replace(",", "")
        # Quitar "vs." o "vs"
        normalized = normalized.replace("vs.", "vs")
        # Quitar espacios extra
        normalized = re.sub(r'\s+', ' ', normalized)

        # Separar por "vs" y ordenar equipos alfabéticamente
        parts = normalized.split(" vs ")
        if len(parts) == 2:
            team_a = parts[0].strip()
            team_b = parts[1].strip()
            # Ordenar alfabéticamente para que el orden sea consistente
            if team_a > team_b:
                team_a, team_b = team_b, team_a
            # Reemplazar espacios por guiones en cada equipo
            team_a = team_a.replace(" ", "-")
            team_b = team_b.replace(" ", "-")
            normalized = f"{team_a}-vs-{team_b}"
        else:
            # Reemplazar espacios por guiones
            normalized = normalized.replace(" ", "-")

        return normalized

    # ============================================================
    # POLYMARKET
    # ============================================================
    async def _run_polymarket(self):
        """Conecta a Polymarket y alimenta el tracker con mercados deportivos."""
        print("[MultiPlatform-Polymarket] Conectando a Polymarket REST API...")
        self._polymarket_connected = True

        def fetch_polymarket():
            import urllib.request
            import json as _json
            url = "https://clob.polymarket.com/markets"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as response:
                return _json.loads(response.read().decode("utf-8"))

        def fetch_book(token_id):
            import urllib.request
            import json as _json
            book_url = f"https://clob.polymarket.com/book?token_id={token_id}"
            book_req = urllib.request.Request(book_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(book_req, timeout=5) as book_resp:
                return _json.loads(book_resp.read().decode("utf-8"))

        while self.running:
            try:
                # Ejecutar requests bloqueantes en un thread pool
                cycle_updates = 0
                result = await asyncio.to_thread(fetch_polymarket)

                sports_keywords = ["NBA", "NFL", "NHL", "MLB", "Soccer", "Tennis", "UFC", "MMA", "NCAAB", "NCAAF"]
                sports_markets = []

                for market in result.get("data", []):
                    question = market.get("question", "")
                    tokens = market.get("tokens", [])

                    is_sport = any(keyword.lower() in question.lower() for keyword in sports_keywords)
                    if is_sport and tokens and len(tokens) >= 2:
                        sports_markets.append(market)

                sports_count = 0
                for market in sports_markets[:20]:
                    tokens = market.get("tokens", [])
                    question = market.get("question", "")

                    if len(tokens) >= 2:
                        yes_token = tokens[0]
                        yes_token_id = yes_token.get("token_id", "")

                        if yes_token_id:
                            try:
                                book = await asyncio.to_thread(fetch_book, yes_token_id)

                                bids = book.get("bids", [])
                                asks = book.get("asks", [])

                                if bids and asks:
                                    best_bid = float(bids[0]["price"])
                                    best_ask = float(asks[0]["price"])
                                    bid_depth = sum(float(b.get("size", 0)) for b in bids[:5])
                                    ask_depth = sum(float(a.get("size", 0)) for a in asks[:5])

                                    event_id = f"polymarket_{question[:50].replace(' ', '_')}"

                                    self._tracker.update_book(
                                        event_id=event_id,
                                        platform="polymarket",
                                        yes_bid=round(best_bid, 4),
                                        yes_ask=round(best_ask, 4),
                                        bid_depth=bid_depth,
                                        ask_depth=ask_depth,
                                        ts_origin=time.time(),
                                    )
                                    sports_count += 1
                            except Exception:
                                pass

                print(f"[MultiPlatform-Polymarket] Updated {sports_count} sports markets in tracker")

            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[MultiPlatform-Polymarket] Error: {e}")

            await asyncio.sleep(self.poll_interval)

        self._polymarket_connected = False

    # ============================================================
    # KALSHI
    # ============================================================
    async def _run_kalshi(self):
        """Conecta a Kalshi y alimenta el tracker."""
        import json
        import time as _time
        import base64
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding

        key_path = os.getenv("KALSHI_PRIVATE_KEY_PATH", "/app/arb.pem")
        api_key_id = os.getenv("KALSHI_API_KEY_ID")

        if not api_key_id or not os.path.exists(key_path):
            print("[MultiPlatform-Kalshi] Sin credenciales, saltando...")
            return

        with open(key_path, 'rb') as f:
            private_key = serialization.load_pem_private_key(f.read(), password=None)

        def kalshi_request(method, path):
            import urllib.request
            ts = str(int(_time.time() * 1000))
            msg = f'{ts}{method}{path}'.encode()
            sig = private_key.sign(msg, padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH), hashes.SHA256())
            req = urllib.request.Request('https://external-api.kalshi.com' + path, method=method, headers={
                'User-Agent': 'M',
                'KALSHI-ACCESS-KEY': api_key_id,
                'KALSHI-ACCESS-SIGNATURE': base64.b64encode(sig).decode(),
                'KALSHI-ACCESS-TIMESTAMP': ts,
            })
            with urllib.request.urlopen(req, timeout=15) as r:
                return json.loads(r.read())

        print("[MultiPlatform-Kalshi] Conectado a Kalshi API")
        self._kalshi_connected = True

        markets_updated = 0
        while self.running:
            try:
                # Ejecutar requests bloqueantes en un thread pool
                series_list = ['KXATPMATCH', 'KXLOLGAME']

                for series in series_list:
                    # Usar asyncio.to_thread para no bloquear el event loop
                    events = await asyncio.to_thread(kalshi_request, 'GET', '/trade-api/v2/events?limit=10&status=open&series_ticker=' + series)

                    for e in events.get('events', []):
                        ticker = e.get('event_ticker', '')
                        event_title = e.get('title', '')
                        markets = await asyncio.to_thread(kalshi_request, 'GET', '/trade-api/v2/markets?limit=5&status=open&event_ticker=' + ticker)

                        for m in markets.get('markets', []):
                            market_ticker = m.get('ticker', '')
                            market_title = m.get('title', '')
                            vol = float(m.get('volume_fp', 0) or 0)

                            if vol < 100:
                                continue

                            yes_bid = float(m.get('yes_bid_dollars', 0) or 0)
                            yes_ask = float(m.get('yes_ask_dollars', 0) or 0)
                            yes_ask_size = float(m.get('yes_ask_size_fp', 0) or 0)

                            if yes_ask > 0:
                                # Usar nombre normalizado como event_id para emparejar con Limitless
                                normalized_title = self._normalize_match_name(event_title)
                                market_team = market_title.replace('Will ', '').split(' win the ')[0]
                                outcome_id = self._normalize_match_name(market_team)
                                event_id = f"match_{normalized_title}__{outcome_id}"
                                self._tracker.update_book(
                                    event_id=event_id,
                                    platform="kalshi",
                                    yes_bid=round(yes_bid, 4),
                                    yes_ask=round(yes_ask, 4),
                                    ask_depth=yes_ask_size,
                                    ts_origin=_time.time(),
                                )
                                markets_updated += 1
                                cycle_updates += 1
                                # Debug: print first few updates
                                if markets_updated <= 3:
                                    print(f"[MultiPlatform-Kalshi] DEBUG: Updated {event_id} yes_bid={yes_bid} yes_ask={yes_ask}")

                print(f"[MultiPlatform-Kalshi] Updated {cycle_updates} markets this cycle (total={markets_updated})")

            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[MultiPlatform-Kalshi] Error: {e}")

            await asyncio.sleep(self.poll_interval)

        self._kalshi_connected = False

    # ============================================================
    # STATUS
    # ============================================================
    def get_status(self) -> dict:
        """Retorna el estado de las conexiones."""
        return {
            "limitless": self._limitless_connected,
            "polymarket": self._polymarket_connected,
            "kalshi": self._kalshi_connected,
        }
