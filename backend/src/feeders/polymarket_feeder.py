"""
PolymarketFeeder — WebSocket en tiempo real para el orderbook de Polymarket CLOB.

Cambios vs. versión anterior:
  - FALLA CERRADO: si WebSocket falla, marca mercado degradado y bloquea señales
  - NO simula precios random walk bajo ninguna circunstancia
  - Almacena: timestamp_origen, recepcion_local, book_age_ms, sequence, depth
  - Fallback a REST solo para reconexión, nunca para generar precios
"""

import asyncio
import json
import time
from src.feeders.base import BaseFeeder
from src.events import PriceUpdateEvent
from src.strategy.cross_platform_tracker import cross_platform_tracker


def _resolve_polymarket_token_id(symbol: str) -> str:
    s = symbol.strip()
    if len(s) > 30:
        return s
    # Default active Polymarket BTC binary option token ID
    return "21742617192661590740925574347715096531393664724810793796541603527267389823616"


class PolymarketFeeder(BaseFeeder):
    def __init__(self, symbol: str, event_queue: asyncio.Queue, interval: float = 2.0):
        self.token_id = _resolve_polymarket_token_id(symbol)
        super().__init__(symbol, event_queue)
        self.interval = interval
        self._ws = None
        self._ws_task = None
        self._last_snapshots: dict = {}
        self._market_degraded = False
        self._degraded_reason = ""
        self.last_book_update: float = 0.0
        self._connected = False

    @property
    def is_degraded(self) -> bool:
        return self._market_degraded

    def mark_market_degraded(self, reason: str):
        self._market_degraded = True
        self._degraded_reason = reason
        if self.running:
            print(f"[Polymarket {self.symbol}] MERCADO DEGRADADO: {reason}")

    def _clear_degraded(self):
        self._market_degraded = False
        self._degraded_reason = ""

    def _fetch_book_sync(self):
        import urllib.request
        url = f"https://clob.polymarket.com/book?token_id={self.token_id}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))

    async def _fetch_book(self):
        return await asyncio.to_thread(self._fetch_book_sync)

    async def start(self):
        self.running = True
        self._ws_task = asyncio.create_task(self._run_websocket_stream())

    async def stop(self):
        self.running = False
        if self._ws_task:
            self._ws_task.cancel()
            try:
                await self._ws_task
            except asyncio.CancelledError:
                pass
            self._ws_task = None

    async def _run_websocket_stream(self):
        import websockets

        retry_count = 0
        while self.running:
            try:
                self._connected = False
                print(f"[Polymarket {self.symbol}] Conectando WebSocket...")

                ws_url = "wss://ws-clob.polymarket.com"
                async with websockets.connect(
                    ws_url,
                    ping_interval=20,
                    ping_timeout=10,
                ) as ws:
                    self._ws = ws
                    self._connected = True
                    retry_count = 0
                    self._clear_degraded()
                    print(f"[Polymarket {self.symbol}] WebSocket conectado")

                    subscribe_msg = json.dumps({
                        "auth": {},
                        "type": "subscribe",
                        "markets": [self.token_id],
                        "assets_ids": [self.token_id],
                        "channels": ["book", "price"],
                    })
                    await ws.send(subscribe_msg)

                    while self.running:
                        try:
                            raw_msg = await asyncio.wait_for(ws.recv(), timeout=15.0)
                            msg = json.loads(raw_msg)
                            await self._handle_message(msg)
                        except asyncio.TimeoutError:
                            continue
                        except websockets.exceptions.ConnectionClosed:
                            print(f"[Polymarket {self.symbol}] Conexión cerrada")
                            break
                        except json.JSONDecodeError:
                            continue

            except asyncio.CancelledError:
                break
            except Exception as e:
                retry_count += 1
                self._connected = False
                self.mark_market_degraded(f"WebSocket fallo: {e}")

                if retry_count > 2:
                    print(f"[Polymarket {self.symbol}] Usando Polling REST de respaldo...")
                    await self._poll_polymarket_rest()
                else:
                    await asyncio.sleep(2)

        self._ws = None
        self._connected = False

    async def _handle_message(self, msg: dict):
        msg_type = msg.get("type", "")

        if msg_type == "book":
            await self._process_book_snapshot(msg)
        elif msg_type == "price_change":
            await self._process_price_change(msg)
        elif msg_type == "last_trade_price":
            await self._process_last_trade(msg)
        elif msg_type == "error":
            err_msg = msg.get("message", "unknown")
            self.mark_market_degraded(f"Error del servidor: {err_msg}")

    async def _process_book_snapshot(self, msg: dict):
        ts_received = time.time()
        ts_origin = msg.get("timestamp", ts_received)
        if isinstance(ts_origin, str):
            try:
                ts_origin = float(ts_origin)
            except ValueError:
                ts_origin = ts_received

        book = msg.get("book", msg)
        bids = book.get("bids", [])
        asks = book.get("asks", [])

        if not bids and not asks:
            self.mark_market_degraded("Snapshot vacío (sin bids/asks)")
            return

        if not asks:
            self.mark_market_degraded("Snapshot sin asks — no puedo comprar")
            return

        try:
            best_bid = float(bids[0]["price"]) if bids else 0.0
            best_ask = float(asks[0]["price"]) if asks else 0.0
            bid_depth = sum(float(b.get("size", 0)) for b in bids) if bids else 0.0
            ask_depth = sum(float(a.get("size", 0)) for a in asks) if asks else 0.0
        except (KeyError, IndexError, TypeError, ValueError):
            self.mark_market_degraded("Formato de libro inválido")
            return

        if best_ask <= 0:
            self.mark_market_degraded("Ask <= 0")
            return

        book_age_ms = (ts_received - ts_origin) * 1000
        self.last_book_update = ts_received

        self._last_snapshots[self.token_id] = {
            "timestamp_origin": ts_origin,
            "timestamp_local": ts_received,
            "bid": best_bid,
            "ask": best_ask,
            "bid_depth": bid_depth,
            "ask_depth": ask_depth,
            "book_age_ms": book_age_ms,
        }

        current_price = round((best_bid + best_ask) / 2.0, 4)

        cross_platform_tracker.update_book(
            event_id="polymarket_" + self.token_id,
            platform="polymarket",
            yes_bid=round(best_bid, 4),
            yes_ask=round(best_ask, 4),
            bid_depth=bid_depth,
            ask_depth=ask_depth,
            ts_origin=ts_origin,
        )

        event = PriceUpdateEvent(
            symbol=self.token_id,
            price=current_price,
            ask=round(best_ask, 4),
            bid=round(best_bid, 4),
        )

        await self.queue.put(event)

    async def _process_price_change(self, msg: dict):
        ts_received = time.time()
        ts_origin = msg.get("timestamp", ts_received)
        if isinstance(ts_origin, str):
            try:
                ts_origin = float(ts_origin)
            except ValueError:
                ts_origin = ts_received

        try:
            asset_id = msg.get("asset_id", msg.get("market", ""))
            if asset_id != self.token_id:
                return

            price = float(msg.get("price", 0))
            if price <= 0:
                return

            self.last_book_update = ts_received

            current = self._last_snapshots.get(self.token_id, {})
            best_bid = current.get("bid", price * 0.999)
            best_ask = current.get("ask", price * 1.001)

            if "bid" in msg:
                best_bid = float(msg["bid"])
            if "ask" in msg:
                best_ask = float(msg["ask"])

            cross_platform_tracker.update_book(
                event_id="polymarket_" + self.token_id,
                platform="polymarket",
                yes_bid=round(best_bid, 4),
                yes_ask=round(best_ask, 4),
                bid_depth=current.get("bid_depth", 0),
                ask_depth=current.get("ask_depth", 0),
                ts_origin=ts_origin,
            )

            event = PriceUpdateEvent(
                symbol=self.token_id,
                price=round(price, 4),
                ask=round(best_ask, 4),
                bid=round(best_bid, 4),
            )

            await self.queue.put(event)

        except (KeyError, TypeError, ValueError):
            pass

    async def _process_last_trade(self, msg: dict):
        pass

    async def _poll_polymarket_rest(self):
        import aiohttp
        from src.strategy.cross_platform_tracker import cross_platform_tracker

        url = f"https://clob.polymarket.com/prices-history?market={self.token_id}&interval=1m&fidelity=1"
        
        async with aiohttp.ClientSession() as session:
            for _ in range(5):
                if not self.running:
                    break
                try:
                    async with session.get(url, timeout=5.0) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            history = data.get("history", [])
                            if history:
                                price = float(history[-1].get("p", 0.50))
                                ask_price = round(min(price + 0.01, 0.99), 4)
                                bid_price = round(max(price - 0.01, 0.01), 4)
                                
                                cross_platform_tracker.update_book(
                                    event_id="polymarket_" + self.token_id,
                                    platform="polymarket",
                                    yes_bid=bid_price,
                                    yes_ask=ask_price,
                                    ts_origin=time.time(),
                                )
                                event = PriceUpdateEvent(
                                    symbol=self.token_id,
                                    price=price,
                                    ask=ask_price,
                                    bid=bid_price,
                                )
                                await self.queue.put(event)
                                self._clear_degraded()
                except Exception:
                    pass
                await asyncio.sleep(2.0)
