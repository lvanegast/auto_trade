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
from src.utils.event_id import make_match_event_id


# Estado global del circuit-breaker de Kalshi (compartido entre ciclos del feeder)
_kalshi_429_streak = 0
_kalshi_pause_until = 0.0


class KalshiRateLimited(Exception):
    """Kalshi devolvió HTTP 429 Too Many Requests tras agotar reintentos."""


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
        self._sx_bet_connected = False

        # Importar tracker aquí para asegurar que usamos la misma instancia
        from src.strategy.cross_platform_tracker import cross_platform_tracker
        self._tracker = cross_platform_tracker

    async def start(self):
        self.running = True
        print("[MultiPlatform] Iniciando conexiones a Limitless, Polymarket, Kalshi y SX Bet...")
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
        """Ejecuta las 4 conexiones en paralelo."""
        try:
            await asyncio.gather(
                self._run_limitless(),
                self._run_polymarket(),
                self._run_kalshi(),
                self._run_sx_bet(),
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

            # Strict Intraday Horizon Filter: Reject events > 48h into the future
            try:
                parts = slug.split("-")
                ts_str = parts[-1]
                if ts_str.isdigit():
                    ts_val = int(ts_str)
                    expiration_s = ts_val / 1000.0 if ts_val > 1000000000000 else float(ts_val)
                    if (time.time() - expiration_s) > 86400 or (expiration_s - time.time()) > 172800:
                        continue
            except Exception:
                pass

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
                            # Use shared canonical event_id for cross-platform matching
                            event_id = make_match_event_id(title, sub_title)
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
                    # Use shared canonical event_id for cross-platform matching
                    event_id = make_match_event_id(title, f"{title} YES")
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
            # Emit a PriceUpdateEvent to trigger Worker 2's strategy
            # Use the first market's price as a reference tick
            if markets:
                first = markets[0]
                first_slug = first.slug if hasattr(first, "slug") else ""
                first_prices = getattr(first, "prices", None)
                if first_prices:
                    price = float(first_prices[0])
                    event = PriceUpdateEvent(
                        symbol=f"multi_platform_tick",
                        price=price,
                        ask=price,
                        bid=price,
                    )
                    await self.queue.put(event)
                # Si no hay precio real, no emitir el tick — el tracker ya se
                # actualizó arriba con datos reales del book; este evento es solo
                # el disparador para evaluate_signal, no debe inventar un precio.

    def _normalize_match_name(self, title: str) -> str:
        """Normaliza nombre de match para emparejar Limitless y Kalshi."""
        import re
        normalized = title.lower().strip()
        
        # Quitar prefijos comunes como 'FRND, ', 'FRIENDLIES - ', etc.
        if "," in normalized:
            normalized = normalized.split(",")[-1].strip()
        if ":" in normalized:
            normalized = normalized.split(":")[-1].strip()
            
        normalized = normalized.replace(".", "").replace(",", "")
        normalized = normalized.replace("vs.", "vs")
        
        # Traducción / homologación de sinónimos de equipos comunes
        synonyms = {
            "münchen": "munich",
            "muenchen": "munich",
            "bayern münchen": "bayern munich",
            "bayern muenchen": "bayern munich",
        }
        for k, v in synonyms.items():
            normalized = normalized.replace(k, v)

        normalized = re.sub(r'\s+', ' ', normalized)

        # Separar por "vs" y ordenar equipos alfabéticamente
        parts = normalized.split(" vs ")
        if len(parts) == 2:
            team_a = parts[0].strip()
            team_b = parts[1].strip()
            if team_a > team_b:
                team_a, team_b = team_b, team_a
            team_a = team_a.replace(" ", "-")
            team_b = team_b.replace(" ", "-")
            normalized = f"{team_a}-vs-{team_b}"
        else:
            normalized = normalized.replace(" ", "-")

        return normalized

    # ============================================================
    # POLYMARKET US (gateway.polymarket.us) — deportes match-level
    # ============================================================
    # Leagues deportivas con mercados match-level en Polymarket US.
    _POLYMARKET_LEAGUES = [
        "nfl", "nba", "mlb", "nhl", "mls", "wnba", "ufc",
        "ucl", "epl", "atp", "wta", "cbb", "cfb",
    ]

    async def _run_polymarket(self):
        """Conecta a Polymarket US (gateway.polymarket.us) y alimenta el tracker
        con mercados deportivos match-level (moneyline/spread/total/props)."""
        print("[MultiPlatform-Polymarket] Conectando a Polymarket US (gateway.polymarket.us)...")
        self._polymarket_connected = True

        def fetch_json(url, timeout=15):
            import urllib.request
            import json as _json
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return _json.loads(response.read().decode("utf-8"))

        def fetch_leagues():
            out = {}
            for league in self._POLYMARKET_LEAGUES:
                url = (
                    f"https://gateway.polymarket.us/v2/leagues/{league}/events"
                    f"?active=true&closed=false&limit=10"
                )
                try:
                    out[league] = fetch_json(url)
                except Exception as e:
                    print(f"[MultiPlatform-Polymarket] League {league} error: {type(e).__name__}: {e}")
            return out

        while self.running:
            try:
                cycle_updates = 0
                leagues_data = await asyncio.to_thread(fetch_leagues)

                for league, data in leagues_data.items():
                    events = data.get("events", []) or []
                    for ev in events:
                        if not self.running:
                            break
                        event_title = ev.get("title", "") or ""
                        if not event_title:
                            continue
                        markets = ev.get("markets", []) or []
                        for market in markets:
                            # Solo moneyline (winner del partido) — matchea 1:1 con
                            # los outcomes de Limitless. Spreads/totals usarían el
                            # mismo team.name y colisionarían el event_id.
                            if market.get("marketType") != "moneyline":
                                continue
                            sides = market.get("marketSides", []) or []
                            if len(sides) < 2:
                                continue
                            # Precios ejecutables del contrato (best bid/ask del instrumento)
                            try:
                                best_bid = float(market["bestBidQuote"]["value"])
                                best_ask = float(market["bestAskQuote"]["value"])
                            except (KeyError, TypeError, ValueError):
                                continue
                            if best_ask <= 0 or best_bid <= 0 or best_ask < best_bid:
                                continue

                            # Equipos de cada lado (long=True = YES / instrumento principal)
                            side_long = next((s for s in sides if s.get("long")), None)
                            side_short = next((s for s in sides if not s.get("long")), None)
                            team_long = (side_long or {}).get("team", {}).get("name", "")
                            team_short = (side_short or {}).get("team", {}).get("name", "")

                            # NO del instrumento: NO_ask = 1 - YES_bid ; NO_bid = 1 - YES_ask
                            no_ask = round(1.0 - best_bid, 4)
                            no_bid = round(1.0 - best_ask, 4)

                            # event_id CANÓNICO: el que usa Limitless para el winner
                            # depende de la representación del partido:
                            #   - Grupo/sub-markets (fútbol/esports):  match_X__<team>
                            #   - Mercado individual binario (tenis):   match_X__<X>-yes
                            # Publicamos AMBAS representaciones para cubrir las dos.
                            # El book YES corresponde al team long; el NO al team short.
                            book_yes = {
                                "event_id": make_match_event_id(event_title, f"{event_title} YES"),
                                "yes_bid": round(best_bid, 4),
                                "yes_ask": round(best_ask, 4),
                                "no_bid": no_bid,
                                "no_ask": no_ask,
                                "bid_depth": float(market.get("bestBidSize") or 0) or 0.0,
                                "ask_depth": float(market.get("bestAskSize") or 0) or 0.0,
                            }
                            book_no = {
                                "event_id": make_match_event_id(event_title, f"{event_title} NO"),
                                "yes_bid": no_bid,
                                "yes_ask": no_ask,
                                "no_bid": round(best_bid, 4),
                                "no_ask": round(best_ask, 4),
                                "bid_depth": float(market.get("bestAskSize") or 0) or 0.0,
                                "ask_depth": float(market.get("bestBidSize") or 0) or 0.0,
                            }

                            publications = [
                                book_yes, book_no,
                                # Representación por equipo (grupo)
                                {
                                    "event_id": make_match_event_id(event_title, team_long),
                                    **book_yes,
                                },
                                {
                                    "event_id": make_match_event_id(event_title, team_short),
                                    **book_no,
                                },
                            ]
                            for pub in publications:
                                if not pub["event_id"]:
                                    continue
                                self._tracker.update_book(
                                    event_id=pub["event_id"],
                                    platform="polymarket",
                                    yes_bid=pub["yes_bid"],
                                    yes_ask=pub["yes_ask"],
                                    no_bid=pub["no_bid"],
                                    no_ask=pub["no_ask"],
                                    bid_depth=pub["bid_depth"],
                                    ask_depth=pub["ask_depth"],
                                    ts_origin=time.time(),
                                )
                                cycle_updates += 1

                if cycle_updates > 0:
                    print(f"[MultiPlatform-Polymarket] Updated {cycle_updates} sports markets in tracker")

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
        private_key_b64 = os.getenv("KALSHI_PRIVATE_KEY_B64", "")

        if not api_key_id:
            print("[MultiPlatform-Kalshi] Sin credenciales, saltando...")
            return

        # Load private key from env var (base64-encoded PEM) or file
        try:
            if private_key_b64:
                import base64
                pem_bytes = base64.b64decode(private_key_b64)
                private_key = serialization.load_pem_private_key(pem_bytes, password=None)
                print("[MultiPlatform-Kalshi] Private key loaded from env var")
            elif os.path.exists(key_path):
                with open(key_path, 'rb') as f:
                    private_key = serialization.load_pem_private_key(f.read(), password=None)
                print("[MultiPlatform-Kalshi] Private key loaded from file")
            else:
                print("[MultiPlatform-Kalshi] Sin credenciales, saltando...")
                return
        except Exception as e:
            print(f"[MultiPlatform-Kalshi] Error loading private key: {e}")
            return

        def kalshi_request(method, path, retries=3):
            import urllib.request
            import urllib.error
            ts = str(int(_time.time() * 1000))
            msg = f'{ts}{method}{path}'.encode()
            sig = private_key.sign(msg, padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH), hashes.SHA256())
            for attempt in range(retries):
                try:
                    req = urllib.request.Request('https://external-api.kalshi.com' + path, method=method, headers={
                        'User-Agent': 'M',
                        'KALSHI-ACCESS-KEY': api_key_id,
                        'KALSHI-ACCESS-SIGNATURE': base64.b64encode(sig).decode(),
                        'KALSHI-ACCESS-TIMESTAMP': ts,
                    })
                    with urllib.request.urlopen(req, timeout=15) as r:
                        return json.loads(r.read())
                except urllib.error.HTTPError as e:
                    if e.code == 429 and attempt < retries - 1:
                        # Backoff exponencial: 2s, 4s
                        _time.sleep(2 ** (attempt + 1))
                        continue
                    if e.code == 429:
                        raise KalshiRateLimited()
                    raise

        print("[MultiPlatform-Kalshi] Conectado a Kalshi API")
        self._kalshi_connected = True

        markets_updated = 0
        while self.running:
            # Circuit-breaker: si hubo 429 repetidos, pausar el loop de Kalshi
            global _kalshi_429_streak, _kalshi_pause_until
            if _time.time() < _kalshi_pause_until:
                await asyncio.sleep(min(5.0, _kalshi_pause_until - _time.time()))
                continue
            try:
                # Ejecutar requests bloqueantes en un thread pool
                cycle_updates = 0
                series_list = [
                    'KXSOCCERSPREAD',  # Soccer Spreads / Friendlies
                    'KXSOCCERMATCH',   # Soccer Matches
                    'KXEPLMATCH',      # Premier League Matches
                    'KXCLUBFRIENDLIES',# Club Friendlies (Bayern vs Aston Villa, etc)
                    'KXFRIENDLIES',    # International Friendlies
                    'KXUEFAEURO',      # UEFA Euro / Champions
                    'KXATPMATCH',      # ATP Tennis
                    'KXLOLGAME',       # League of Legends
                    'KXCSGOMATCH',     # CS2
                    'KXVALMATCH',      # Valorant
                    'KXDOTAMATCH',     # Dota 2
                    'KXNBA',           # NBA
                    'KXNHL',           # NHL
                    'KXMLB',           # MLB
                    'KXNFL',           # NFL
                    'KXUFCMATCH',      # UFC
                ]

                for series in series_list:
                    if not self.running:
                        break
                    try:
                        events = await asyncio.to_thread(kalshi_request, 'GET', '/trade-api/v2/events?limit=5&status=open&series_ticker=' + series)
                    except KalshiRateLimited:
                        _kalshi_429_streak += 1
                        print(f"[MultiPlatform-Kalshi] 429 en serie {series} (streak={_kalshi_429_streak})")
                        if _kalshi_429_streak >= 3:
                            _kalshi_pause_until = _time.time() + 120
                            print("[MultiPlatform-Kalshi] 429 repetido — pausando 120s (circuit breaker)")
                            _kalshi_429_streak = 0
                        break

                    _kalshi_429_streak = 0

                    for e in events.get('events', []):
                        if not self.running:
                            break
                        ticker = e.get('event_ticker', '')
                        event_title = e.get('title', '')
                        try:
                            markets = await asyncio.to_thread(kalshi_request, 'GET', '/trade-api/v2/markets?limit=5&status=open&event_ticker=' + ticker)
                        except KalshiRateLimited:
                            _kalshi_429_streak += 1
                            if _kalshi_429_streak >= 3:
                                _kalshi_pause_until = _time.time() + 120
                                print("[MultiPlatform-Kalshi] 429 repetido — pausando 120s (circuit breaker)")
                                _kalshi_429_streak = 0
                            break
                        _kalshi_429_streak = 0

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
                                # Use shared canonical event_id for cross-platform matching
                                event_id = make_match_event_id(event_title, market_title)
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

                        # Throttle: evita ráfagas entre mercados de un evento
                        await asyncio.sleep(0.15)

                    # Throttle: evita ráfagas entre series
                    await asyncio.sleep(0.3)

                print(f"[MultiPlatform-Kalshi] Updated {cycle_updates} markets this cycle (total={markets_updated})")

            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[MultiPlatform-Kalshi] Error: {e}")

            await asyncio.sleep(self.poll_interval)

        self._kalshi_connected = False

    # ============================================================
    # SX BET (api.sx.bet) — exchange binario de deportes en USDC
    # ============================================================
    # SX Bet es un exchange P2P de deportes: cada mercado tiene exactamente
    # 2 outcomes (outcomeOneName / outcomeTwoName) y cada orden es una compra
    # de UNO de ellos (isMakerBettingOutcomeOne). El "lay" de Betfair equivale
    # aquí a comprar el outcome contrario → encaja 1:1 con el modelo YES/NO.
    #
    # Conversión de precios (ver docs oficiales orderbook-core):
    #   - percentageOdds es la cuota IMPLÍCITA del maker, escala 1e20.
    #   - El taker recibe el outcome contrario a takerOdds = 1 - p/1e20.
    #   - Best ask para outcome 1: fill del maker de outcome 2 con MAX p.
    #   - Best bid para outcome 1: fill del maker de outcome 1 con MAX p.
    #   - Liquidez del taker: (totalBetSize - fillAmount - pendingFillAmount)
    #       * 1e20 / percentageOdds - (totalBetSize - fillAmount - pendingFillAmount)
    # Comisión: 0% maker y taker en singles. Settlement on-chain USDC.
    #
    # Market types relevantes (moneyline = equivalente a winner de Limitless):
    #   52  = "12" (moneyline, sin empate)
    #   226 = "12 Including Overtime"
    _SX_BET_BASE = "https://api.sx.bet"
    _SX_BET_MONEYLINE_TYPES = (52, 226)
    _SX_BET_SCALE = 10 ** 20

    async def _run_sx_bet(self):
        """Conecta a SX Bet (api.sx.bet) y alimenta el tracker con mercados
        moneyline binarios (deportes match-level). Sin API key para reads."""
        import json
        import urllib.request
        import urllib.error

        def fetch_json(url, timeout=15):
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        print("[MultiPlatform-SXBet] Conectando a SX Bet (api.sx.bet)...")
        self._sx_bet_connected = True

        while self.running:
            try:
                cycle_updates = 0
                # 1. Mercados activos (moneyline)
                markets_url = (
                    f"{self._SX_BET_BASE}/markets/active?pageSize=100"
                    f"&gameTime={int(time.time())}"
                )
                resp = await asyncio.to_thread(fetch_json, markets_url)
                markets = (resp.get("data", {}) or {}).get("markets", []) or []

                # 2. Filtrar solo moneyline binario y en ventana de 48h
                candidates = []
                for m in markets:
                    mtype = m.get("type")
                    if mtype not in self._SX_BET_MONEYLINE_TYPES:
                        continue
                    status = m.get("status", "")
                    if status and status != "ACTIVE":
                        continue
                    game_time = m.get("gameTime") or 0
                    if game_time and (abs(time.time() - game_time) > 172800):
                        continue
                    candidates.append(m)

                if candidates:
                    # 3. Orderbooks de cada mercado (agrupados para reducir llamadas)
                    batch = [c["marketHash"] for c in candidates if c.get("marketHash")]
                    if batch:
                        try:
                            ob_url = (
                                f"{self._SX_BET_BASE}/orders?marketHashes={','.join(batch)}"
                                f"&perPage=1000"
                            )
                            ob_resp = await asyncio.to_thread(fetch_json, ob_url)
                            orders = ob_resp.get("data", []) or []
                        except Exception as e:
                            orders = []
                            print(f"[MultiPlatform-SXBet] Orderbook error: {type(e).__name__}: {e}")

                        by_market: dict = {}
                        for o in orders:
                            by_market.setdefault(o.get("marketHash"), []).append(o)

                        for m in candidates:
                            mhash = m.get("marketHash")
                            m_orders = by_market.get(mhash, [])
                            if not m_orders:
                                continue
                            book = self._sx_bet_build_book(m, m_orders)
                            if book is None:
                                continue
                            if not hasattr(self, "_sx_bet_debug_count"):
                                self._sx_bet_debug_count = 0
                            if self._sx_bet_debug_count < 8:
                                print(
                                    f"[MultiPlatform-SXBet] DEBUG: "
                                    f"{m.get('outcomeOneName')} vs {m.get('outcomeTwoName')} "
                                    f"type={m.get('type')} -> "
                                    f"event_ids={book['event_ids']} "
                                    f"yes_ask={book['book']['yes_ask']} yes_bid={book['book']['yes_bid']}"
                                )
                                self._sx_bet_debug_count += 1
                            for event_id in book["event_ids"]:
                                self._tracker.update_book(
                                    event_id=event_id,
                                    platform="sx_bet",
                                    yes_bid=book["book"]["yes_bid"],
                                    yes_ask=book["book"]["yes_ask"],
                                    no_bid=book["book"]["no_bid"],
                                    no_ask=book["book"]["no_ask"],
                                    bid_depth=book["book"]["bid_depth"],
                                    ask_depth=book["book"]["ask_depth"],
                                    ts_origin=time.time(),
                                )
                                cycle_updates += 1

                if cycle_updates > 0:
                    print(f"[MultiPlatform-SXBet] Updated {cycle_updates} moneyline markets in tracker")

            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[MultiPlatform-SXBet] Error: {type(e).__name__}: {e}")

            await asyncio.sleep(self.poll_interval)

        self._sx_bet_connected = False

    def _sx_bet_build_book(self, market: dict, orders: list) -> dict | None:
        """Construye el book ejecutable YES/NO de un mercado moneyline de SX Bet.

        Un mercado moneyline tiene outcomeOneName = equipo/player 1 (YES) y
        outcomeTwoName = equipo/player 2 (NO).

        Rules (orderbook-core):
          - Maker con isMakerBettingOutcomeOne=True  → apostó outcome 1 (YES)
          - Maker con isMakerBettingOutcomeOne=False → apostó outcome 2 (NO)
          - El taker que llena al maker apuesta el outcome CONTRARIO.
          - Llenar un maker de NO → yo compro YES a (1 - p_no/1e20).
          - Llenar un maker de YES → yo compro NO a (1 - p_yes/1e20).

        Best executable:
          - yes_ask = 1 - max(p_no)  (el maker de NO más agresivo me vende YES más barato)
          - yes_bid = 1 - max(p_yes) (el maker de YES más agresivo me paga NO más alto)
        """
        outcome_one = (market.get("outcomeOneName") or "").strip()
        outcome_two = (market.get("outcomeTwoName") or "").strip()
        if not outcome_one or not outcome_two:
            return None

        best_p_yes = None   # makers apostando outcome 1 (compro NO)
        best_p_no = None    # makers apostando outcome 2 (compro YES)
        depth_yes = 0.0
        depth_no = 0.0

        for o in orders:
            status = o.get("orderStatus", "ACTIVE")
            if status and status != "ACTIVE":
                continue
            try:
                p = float(o.get("percentageOdds")) / self._SX_BET_SCALE
                total = float(o.get("totalBetSize") or 0)
                filled = float(o.get("fillAmount") or 0)
                pending = float(o.get("pendingFillAmount") or 0)
            except (TypeError, ValueError):
                continue
            if p <= 0 or p >= 1:
                continue
            remaining_taker = 0.0
            if total - filled - pending > 0 and p > 0:
                # remainingTakerSpace = remaining * 1e20 / percentageOdds - remaining
                # percentageOdds = p * 1e20 → remaining/p - remaining
                remaining_taker = (total - filled - pending) / p - (total - filled - pending)
                remaining_taker = remaining_taker / 1_000_000.0  # USDC: 6 decimales → USD

            if o.get("isMakerBettingOutcomeOne") is True:
                if best_p_yes is None or p > best_p_yes:
                    best_p_yes = p
                    depth_yes = remaining_taker
            else:
                if best_p_no is None or p > best_p_no:
                    best_p_no = p
                    depth_no = remaining_taker

        if best_p_yes is None or best_p_no is None:
            return None

        yes_ask = round(1.0 - best_p_no, 4)
        yes_bid = round(1.0 - best_p_yes, 4)
        if yes_ask <= 0 or yes_bid <= 0 or yes_ask <= yes_bid:
            return None

        no_bid = round(1.0 - yes_ask, 4)
        no_ask = round(1.0 - yes_bid, 4)

        # Event ID canónico: reconstruimos el título del match (mismo formato
        # que Limitless para moneyline: "Liudmila Samsonova vs Elena Rybakina")
        # y publicamos la representación winner (match_X__X-yes) que es la que
        # usa Limitless para tenis, más la representación por equipo.
        match_title = f"{outcome_one} vs {outcome_two}"
        event_ids = [
            make_match_event_id(match_title, f"{match_title} YES"),
            make_match_event_id(match_title, outcome_one),
        ]
        book = {
            "yes_bid": yes_bid,
            "yes_ask": yes_ask,
            "no_bid": no_bid,
            "no_ask": no_ask,
            "bid_depth": depth_yes,
            "ask_depth": depth_no,
        }
        return {"event_ids": event_ids, "book": book}

    # ============================================================
    # STATUS
    # ============================================================
    def get_status(self) -> dict:
        """Retorna el estado de las conexiones."""
        return {
            "limitless": self._limitless_connected,
            "polymarket": self._polymarket_connected,
            "kalshi": self._kalshi_connected,
            "sx_bet": self._sx_bet_connected,
        }
