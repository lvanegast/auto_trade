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
from limitless_sdk.market_pages import MarketPageFetcher
from src.utils.event_id import make_match_event_id


import time

# Shared cache to prevent Cloudflare HTTP 429 rate limit across multiple worker feeders
_last_sports_scan_time = 0.0
_sports_scan_lock = asyncio.Lock()


class LimitlessSportsFeeder(BaseFeeder):
    def __init__(self, symbol: str, event_queue: asyncio.Queue):
        super().__init__(symbol.upper(), event_queue)
        self.poll_interval = float(os.getenv("SPORTS_POLL_INTERVAL", "3.0"))
        self.min_volume = float(os.getenv("SPORTS_MIN_VOLUME", "100"))
        self.task = None

    async def start(self):
        self.running = True
        print(
            f"[Feeder Limitless Sports] Iniciando polling cada {self.poll_interval}s..."
        )
        try:
            from src.api.app import db
            db.log("INFO", f"[Feeder Limitless Sports] Iniciando polling cada {self.poll_interval}s...", "worker_3")
        except Exception:
            pass
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

        print(f"[Feeder Limitless Sports] _run_polling() started")
        try:
            from src.api.app import db
            db.log("INFO", "[Feeder Limitless Sports] _run_polling() started", "worker_3")
        except Exception:
            pass
        try:
            http_client = HttpClient()
            self._page_fetcher = MarketPageFetcher(http_client)
            self._market_fetcher = MarketFetcher(http_client)
            print(f"[Feeder Limitless Sports] HttpClient initialized successfully")
        except Exception as e:
            print(f"[Feeder Limitless Sports] FATAL: HttpClient init failed: {e}")
            try:
                from src.api.app import db
                db.log("ERROR", f"[Feeder Limitless Sports] FATAL: HttpClient init failed: {e}", "worker_3")
            except Exception:
                pass
            return

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
            try:
                await http_client.close()
            except Exception:
                pass

    async def _scan_sports_markets(self):
        global _last_sports_scan_time
        now = time.time()
        if now - _last_sports_scan_time < 5.0:
            return
        async with _sports_scan_lock:
            _last_sports_scan_time = now
            try:
                from src.engine.latency_tracker import latency_tracker
                
                from limitless_sdk.markets import MarketFetcher
                from limitless_sdk.api import HttpClient

                markets = []
                try:
                    async with HttpClient() as http:
                        page_fetcher = MarketPageFetcher(http)
                        # Fetch both sports and esports pages
                        for path in ["/sport", "/esports"]:
                            try:
                                async with latency_tracker.measure("limitless_sports", f"get_{path}_page") as m:
                                    page = await page_fetcher.get_market_page_by_path(path)
                                    m.result = page
                                resp = await page_fetcher.get_markets(page.id, {"limit": 50})
                                page_markets = resp.data if hasattr(resp, "data") else []
                                markets.extend(page_markets)
                            except Exception as pe:
                                print(f"[Sports Feeder] Error fetching {path}: {pe}")
                except Exception as pe:
                    if "TimeoutError" not in str(type(pe)) and "Cannot connect" not in str(pe):
                        print(f"[Sports Feeder] Error fetching sports page: {pe}")
                        try:
                            from src.api.app import db
                            db.log("ERROR", f"[Sports Feeder] Error fetching sports page: {pe}", "worker_3")
                        except Exception:
                            pass

                print(f"[Sports Feeder] Fetched {len(markets)} markets from /sport + /esports")
                _stats = {"total": 0, "no_slug": 0, "crypto_filtered": 0, "group_arb": 0, "single_market": 0, "skipped": 0}
                for m in markets:
                    _stats["total"] += 1
                    slug = m.slug if hasattr(m, "slug") else (m.get("slug", "") if isinstance(m, dict) else "")
                    title = m.title if hasattr(m, "title") else (m.get("title", "") if isinstance(m, dict) else "")
                    if not slug:
                        _stats["no_slug"] += 1
                        continue

                    # Filter long-term futures / stale events. Usamos la
                    # expiration_timestamp REAL del mercado (no el ts del slug,
                    # que es la fecha de creación y descartaba partidos lejanos).
                    # El horizonte máximo es configurable (default 14 días) para
                    # no escanear futures de temporada; los partidos a >48h se
                    # evalúan con el umbral de edge alto (SPORTS_FAR_MIN_EDGE_PCT).
                    try:
                        exp_ts = getattr(m, "expiration_timestamp", None) or (m.get("expiration_timestamp") if isinstance(m, dict) else None)
                        if not exp_ts:
                            parts = slug.split("-")
                            ts_str = parts[-1]
                            if ts_str.isdigit():
                                ts_val = int(ts_str)
                                exp_ts = ts_val / 1000.0 if ts_val > 1000000000000 else float(ts_val)
                            else:
                                exp_ts = None
                        if exp_ts:
                            expiration_s = float(exp_ts) / 1000.0 if float(exp_ts) > 1000000000000 else float(exp_ts)
                            max_horizon_h = float(os.getenv("SPORTS_MAX_HORIZON_HOURS", "336"))
                            # Allow matches starting up to max horizon, or started within last 24h (live/in-play)
                            if (now - expiration_s) > 86400 or (expiration_s - now) > (max_horizon_h * 3600.0):
                                _stats["skipped"] += 1
                                continue
                    except Exception:
                        pass

                    # Extract sub-markets directly from item payload without secondary HTTP request
                    subs = getattr(m, "markets", None) or (m.get("markets") if isinstance(m, dict) else None)
                    expiration_ts = getattr(m, "expiration_timestamp", None) or (m.get("expiration_timestamp") if isinstance(m, dict) else None)
                    if subs and isinstance(subs, list) and len(subs) >= 2:
                        _stats["group_arb"] += 1
                        await self._process_group_arb(slug, title, subs, expiration_ts)
                    else:
                        # Single / binary market directly in item
                        prices = getattr(m, "prices", None) or (m.get("prices") if isinstance(m, dict) else None)
                        if prices and len(prices) >= 2:
                            _stats["single_market"] += 1
                            await self._process_single_market(slug, title, prices)
                        else:
                            _stats["skipped"] += 1
                    
                    # Delay entre mercados para evitar rate limiting
                    await asyncio.sleep(0.1)

                print(f"[Sports Feeder] Scan complete: {len(markets)} markets checked | stats: {_stats}")
                try:
                    from src.api.app import db
                    db.log("INFO", f"[Sports Feeder] Scan complete: {len(markets)} markets checked", "worker_3")
                except Exception:
                    pass
            except Exception as e:
                print(f"[Sports] Error escaneando eventos dinámicos: {e}")
                try:
                    from src.api.app import db
                    db.log("ERROR", f"[Sports] Error escaneando eventos dinámicos: {e}", "worker_3")
                except Exception:
                    pass

    async def _process_group_arb(self, group_slug, group_title, subs, expiration_ts=None):
        from src.strategy.cross_platform_tracker import cross_platform_tracker
        from src.limitless_price_cache import async_get_limitless_executable_price

        total_subs = len(subs)
        total_yes = 0
        outcomes = []
        skipped_no_price = 0
        skipped_no_liquidity = 0

        for sub in subs:
            prices = getattr(sub, "prices", None) if hasattr(sub, "prices") else (sub.get("prices") if isinstance(sub, dict) else None)
            if not prices or len(prices) == 0:
                skipped_no_price += 1
                continue
            slug = getattr(sub, "slug", "") if hasattr(sub, "slug") else (sub.get("slug", "") if isinstance(sub, dict) else "")
            title = getattr(sub, "title", "") if hasattr(sub, "title") else (sub.get("title", "") if isinstance(sub, dict) else "")
            try:
                book = await async_get_limitless_executable_price(slug)
                if not book:
                    skipped_no_liquidity += 1
                    continue
                yes_price = book["yes_ask"]
            except (ValueError, TypeError):
                skipped_no_price += 1
                continue

            # Check real liquidity via orderbook
            # If bids == 0 AND asks == 0, this sub-market has no real liquidity
            has_real_liquidity = False
            try:
                from limitless_sdk.markets import MarketFetcher
                from limitless_sdk.api import HttpClient
                
                async with HttpClient() as http:
                    fetcher = MarketFetcher(http)
                    ob = await fetcher.get_orderbook(slug)
                    bids = ob.bids if hasattr(ob, 'bids') else []
                    asks = ob.asks if hasattr(ob, 'asks') else []
                    
                    if len(bids) > 0 and len(asks) > 0:
                        has_real_liquidity = True
                    else:
                        skipped_no_liquidity += 1
            except Exception:
                # If we can't fetch orderbook, assume no liquidity
                skipped_no_liquidity += 1

            if not has_real_liquidity:
                continue

            total_yes += yes_price
            outcomes.append(
                {
                    "slug": slug,
                    "title": title,
                    "yes_price": yes_price,
                    "no_price": 1.0 - yes_price,
                }
            )

        # If ANY sub-market had no real liquidity, discard the entire GROUP
        if skipped_no_liquidity > 0:
            return

        if len(outcomes) < 2 or skipped_no_price > 0:
            return

        edge = 1.0 - total_yes
        if abs(edge) > 0.15:
            return

        # 1xN: edge_NO = total_yes - 1 = -edge_YES. Negative edge means the
        # profitable side is NO. Normalize to the profitable direction.
        arb_type = "YES" if edge >= 0 else "NO"
        gross_edge = round(abs(edge), 4)
        direction_label = "BUY_ALL_YES_1XN" if arb_type == "YES" else "BUY_ALL_NO_1XN"
        entry_price = total_yes if arb_type == "YES" else round(len(outcomes) - total_yes, 4)

        # Dynamic viability threshold: si el partido está a más de 2 días, el
        # edge mínimo exigido sube (SPORTS_FAR_MIN_EDGE_PCT, default 7%) para
        # compensar la espera del capital. Dentro de 2 días se usa el umbral
        # intraday normal (SPORTS_ARB_EDGE_PCT o 2%).
        _now = time.time()
        min_edge_req = float(os.getenv("SPORTS_ARB_EDGE_PCT", "0.02"))
        try:
            if expiration_ts:
                _exp_s = float(expiration_ts) / 1000.0 if float(expiration_ts) > 1000000000000 else float(expiration_ts)
                _hours_to_match = (_exp_s - _now) / 3600.0
                far_threshold_h = float(os.getenv("SPORTS_FAR_MATCH_THRESHOLD_HOURS", "48"))
                if _hours_to_match > far_threshold_h:
                    min_edge_req = float(os.getenv("SPORTS_FAR_MIN_EDGE_PCT", "0.07"))
        except Exception:
            pass

        # IMPORTANTE: make_match_event_id() normaliza solo por nombres de equipo,
        # sin fecha ni identificador de partido — dos partidos REALES distintos
        # entre los mismos equipos (jornadas distintas, ida/vuelta) colisionan en
        # el mismo event_id. Se agrega el group_slug real de Limitless (único por
        # partido) para desambiguar el tracking interno / resolución / Telegram.
        # cross_platform_tracker sigue usando el event_id normalizado (sin slug)
        # abajo, porque ese sí necesita ser platform-agnostic para matchear con
        # Kalshi/Polymarket.
        event_id = f"{make_match_event_id(group_title, group_title)}::{group_slug}"
        primary_price = outcomes[0]["yes_price"]

        # Group data is still published to the tracker only when every outcome
        # has a real executable book. Individual outcome books remain distinct.
        for outcome in outcomes:
            book = await async_get_limitless_executable_price(outcome["slug"])
            if not book:
                return
            cross_platform_tracker.update_book(
                event_id=make_match_event_id(group_title, outcome["title"]),
                platform="limitless",
                yes_bid=book["yes_bid"],
                yes_ask=book["yes_ask"],
                bid_depth=book["bid_size"],
                ask_depth=book["ask_size"],
            )

        from src.strategy.sports_arb import update_sports_edge
        update_sports_edge(
            event_id=event_id,
            total_yes=total_yes,
            edge=edge,
            outcomes_count=len(outcomes),
            title=group_title,
            outcomes=outcomes,
            group_slug=group_slug,
            expiration_ts=expiration_ts,
        )

        try:
            from src.api.app import db
            db.save_edge_snapshot(
                worker_id="worker_3",
                platform_a="limitless",
                platform_b="limitless",
                event_id=event_id,
                event_title=group_title,
                edge_pct=gross_edge,
                gross_edge_pct=gross_edge,
                platform_a_yes_ask=primary_price,
                platform_b_no_ask=1.0 - primary_price,
                platform_a_depth=10.0,
                platform_b_depth=10.0,
                liquidity_verified=True,
                viable=(gross_edge >= min_edge_req),
                direction=direction_label,
                outcomes_count=len(outcomes),
                market_slug=group_slug,
                entry_price=entry_price,
                expected_profit=gross_edge * 2.0,
                category="sports",
            )
        except Exception:
            pass

        event = PriceUpdateEvent(
            symbol=event_id,
            price=primary_price,
            ask=primary_price,
            bid=primary_price,
        )
        await self.queue.put(event)

    async def _process_single_market(self, slug, title, prices):
        from src.strategy.cross_platform_tracker import cross_platform_tracker
        from limitless_sdk.markets import MarketFetcher
        from limitless_sdk.api import HttpClient

        # Fetch real orderbook via SDK (not HTTP cache)
        try:
            async with HttpClient() as http:
                fetcher = MarketFetcher(http)
                ob = await fetcher.get_orderbook(slug)
                bids = ob.bids if hasattr(ob, 'bids') else []
                asks = ob.asks if hasattr(ob, 'asks') else []
                
                if not bids or not asks:
                    return  # No real liquidity
                
                yes_bid = float(bids[0].price)
                yes_ask = float(asks[0].price)
        except Exception:
            return

        no_ask = round(1.0 - yes_bid, 4)
        total_yes = yes_ask + no_ask
        edge = round(1.0 - total_yes, 4)
        if abs(edge) > 0.15:
            return

        # Ver comentario equivalente en _process_group_market: se agrega el slug
        # real para no colisionar con otro partido entre los mismos equipos.
        event_id = f"{make_match_event_id(title, title)}::{slug}"
        cross_platform_tracker.update_book(
            event_id=make_match_event_id(title, f"{title} YES"),
            platform="limitless",
            yes_bid=yes_bid,
            yes_ask=yes_ask,
            bid_depth=float(bids[0].size) if bids else 0,
            ask_depth=float(asks[0].size) if asks else 0,
        )

        from src.strategy.sports_arb import update_sports_edge
        outcomes = [
            {"slug": f"{slug}_YES", "title": f"{title} (YES)", "yes_price": yes_ask, "no_price": no_ask},
            {"slug": f"{slug}_NO", "title": f"{title} (NO)", "yes_price": no_ask, "no_price": yes_ask},
        ]
        update_sports_edge(
            event_id=event_id,
            total_yes=total_yes,
            edge=edge,
            outcomes_count=2,
            title=title,
            outcomes=outcomes,
            group_slug=slug,
        )

        event = PriceUpdateEvent(
            symbol=event_id,
            price=yes_ask,
            ask=yes_ask,
            bid=yes_bid,
        )
        await self.queue.put(event)
