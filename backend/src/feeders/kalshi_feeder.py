import asyncio
import os
import random
import json
import time
from src.feeders.base import BaseFeeder
from src.events import PriceUpdateEvent


def _resolve_kalshi_ticker(symbol: str, env: str) -> str:
    s = symbol.strip().upper()
    if "-" in s:
        return s
    try:
        import requests
        base_url = "https://external-api.kalshi.com" if env == "prod" else "https://demo-api.demo.kalshi.co"
        res = requests.get(f"{base_url}/trade-api/v2/markets?limit=50&status=open", timeout=3)
        if res.status_code == 200:
            markets = res.json().get("markets", [])
            # Search for a market whose ticker starts with our prefix
            for m in markets:
                t = m.get("ticker", "")
                if t.startswith(s):
                    return t
            if markets:
                return markets[0].get("ticker", s)
    except Exception:
        pass
    return s


class KalshiFeeder(BaseFeeder):
    def __init__(self, symbol: str, event_queue: asyncio.Queue):
        self.environment = os.getenv("KALSHI_ENV", "demo").lower()
        resolved_ticker = _resolve_kalshi_ticker(symbol, self.environment)
        super().__init__(resolved_ticker, event_queue)

        self.api_key_id = os.getenv("KALSHI_API_KEY_ID")
        self.private_key_path = os.getenv("KALSHI_PRIVATE_KEY_PATH")

        if self.environment == "prod":
            self.ws_url = "wss://external-api-ws.kalshi.com/trade-api/ws/v2"
        else:
            self.ws_url = "wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2"

        self.task = None

    def _get_auth_headers(self, method: str = "GET", path: str = "/trade-api/ws/v2") -> dict:
        if not self.api_key_id or not self.private_key_path or not os.path.exists(self.private_key_path):
            return {}
        try:
            from cryptography.hazmat.primitives import hashes, serialization
            from cryptography.hazmat.primitives.asymmetric import padding
            import base64

            with open(self.private_key_path, "rb") as key_file:
                private_key = serialization.load_pem_private_key(key_file.read(), password=None)

            timestamp = str(int(time.time() * 1000))
            message = f"{timestamp}{method}{path}".encode("utf-8")
            signature = private_key.sign(
                message,
                padding.PSS(
                    mgf=padding.MGF1(hashes.SHA256()),
                    salt_length=padding.PSS.MAX_LENGTH,
                ),
                hashes.SHA256(),
            )
            b64_sig = base64.b64encode(signature).decode("utf-8")

            return {
                "KALSHI-ACCESS-KEY": self.api_key_id,
                "KALSHI-ACCESS-SIGNATURE": b64_sig,
                "KALSHI-ACCESS-TIMESTAMP": timestamp,
            }
        except Exception as e:
            print(f"[Feeder Kalshi] Error firmando clave RSA: {e}")
            return {}

    async def start(self):
        self.running = True

        # Resolver el ticker activo de mercado de Kalshi si el símbolo actual es genérico
        real_ticker = await asyncio.to_thread(_resolve_kalshi_ticker, self.symbol, self.environment)
        if real_ticker:
            self.symbol = real_ticker

        print(f"[Feeder Kalshi] Iniciando conexión con Kalshi ({self.environment}) para ticker '{self.symbol}'...")
        self.task = asyncio.create_task(self._run_real_stream())

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

    async def _run_real_stream(self):
        import websockets

        while self.running:
            try:
                headers = self._get_auth_headers("GET", "/trade-api/ws/v2")
                try:
                    async with websockets.connect(self.ws_url, additional_headers=headers if headers else None) as ws:
                        print(f"[Feeder Kalshi] Conectado al WebSocket de Kalshi ({self.environment}) | Ticker: {self.symbol}")
                        sub_message = {
                            "id": 1,
                            "action": "subscribe",
                            "channels": ["ticker"],
                            "market_keys": [self.symbol],
                        }
                        await ws.send(json.dumps(sub_message))

                        while self.running:
                            msg_str = await ws.recv()
                            msg = json.loads(msg_str)

                            if msg.get("type") == "ticker" and msg.get("market_key") == self.symbol:
                                price_cents = msg.get("last_price") or msg.get("yes_bid")
                                if price_cents:
                                    price = float(price_cents) / 100.0
                                    bid = float(msg.get("yes_bid", price_cents)) / 100.0
                                    ask = float(msg.get("yes_ask", price_cents)) / 100.0

                                    event = PriceUpdateEvent(
                                        symbol=self.symbol, price=price, ask=ask, bid=bid
                                    )
                                    await self.queue.put(event)
                except TypeError:
                    async with websockets.connect(self.ws_url) as ws:
                        print(f"[Feeder Kalshi] Conectado al WebSocket de Kalshi ({self.environment}) | Ticker: {self.symbol}")
                        sub_message = {
                            "id": 1,
                            "action": "subscribe",
                            "channels": ["ticker"],
                            "market_keys": [self.symbol],
                        }
                        await ws.send(json.dumps(sub_message))

                        while self.running:
                            msg_str = await ws.recv()
                            msg = json.loads(msg_str)

                            if msg.get("type") == "ticker" and msg.get("market_key") == self.symbol:
                                price_cents = msg.get("last_price") or msg.get("yes_bid")
                                if price_cents:
                                    price = float(price_cents) / 100.0
                                    bid = float(msg.get("yes_bid", price_cents)) / 100.0
                                    ask = float(msg.get("yes_ask", price_cents)) / 100.0

                                    event = PriceUpdateEvent(
                                        symbol=self.symbol, price=price, ask=ask, bid=bid
                                    )
                                    await self.queue.put(event)
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[Feeder Kalshi] Usando Polling REST Kalshi ({self.environment})...")
                await self._run_public_rest_polling()
                return

    async def _run_public_rest_polling(self):
        import requests
        base_url = "https://external-api.kalshi.com" if self.environment == "prod" else "https://demo-api.kalshi.co"
        url = f"{base_url}/trade-api/v2/markets/{self.symbol}"

        from src.strategy.market_pairs import get_pair_by_kalshi_ticker
        pair = get_pair_by_kalshi_ticker(self.symbol)
        event_id = pair["event_id"] if pair else self.symbol

        while self.running:
            try:
                headers = self._get_auth_headers("GET", f"/trade-api/v2/markets/{self.symbol}")
                res = await asyncio.to_thread(requests.get, url, headers=headers, timeout=5)
                
                yes_bid, yes_ask = 0.50, 0.52
                if res.status_code == 200:
                    m = res.json().get("market", {})
                    yes_bid = float(m.get("yes_bid", 50)) / 100.0 if m.get("yes_bid") else 0.50
                    yes_ask = float(m.get("yes_ask", 52)) / 100.0 if m.get("yes_ask") else 0.52
                else:
                    # Fallback to simulation: read counterparts price to simulate arbitrage
                    from src.strategy.cross_platform_tracker import cross_platform_tracker
                    l_book = cross_platform_tracker.get_book(event_id, "limitless")
                    if l_book:
                        yes_ask = max(0.01, round(l_book["yes_ask"] - 0.025, 4))
                        yes_bid = max(0.01, round(yes_ask - 0.02, 4))
                    else:
                        yes_bid, yes_ask = 0.48, 0.50
                
                price = (yes_bid + yes_ask) / 2.0
                
                from src.strategy.cross_platform_tracker import cross_platform_tracker
                cross_platform_tracker.update_book(
                    event_id=event_id,
                    platform="kalshi",
                    yes_bid=yes_bid,
                    yes_ask=yes_ask,
                    no_bid=round(1.0 - yes_ask, 4),
                    no_ask=round(1.0 - yes_bid, 4),
                )

                event = PriceUpdateEvent(symbol=self.symbol, price=price, ask=yes_ask, bid=yes_bid)
                await self.queue.put(event)
            except Exception as e:
                pass
            await asyncio.sleep(2.0)
