import asyncio
import os
import random
import json
from src.feeders.base import BaseFeeder
from src.events import PriceUpdateEvent


class KalshiFeeder(BaseFeeder):
    def __init__(self, symbol: str, event_queue: asyncio.Queue):
        # El símbolo de Kalshi suele ser un ticker de contrato, ej: USDA-INFL-26
        super().__init__(symbol.upper(), event_queue)

        self.api_key_id = os.getenv("KALSHI_API_KEY_ID")
        self.private_key_path = os.getenv("KALSHI_PRIVATE_KEY_PATH")
        self.environment = os.getenv("KALSHI_ENV", "demo").lower()

        # Determinar hosts según el entorno
        if self.environment == "prod":
            self.ws_url = "wss://trading-api.kalshi.com/trade-api/v2/websocket"
        else:
            self.ws_url = "wss://demo-api.kalshi.co/trade-api/v2/websocket"

        self.task = None

    async def start(self):
        """Inicia el alimentador de Kalshi."""
        self.running = True

        # Si no hay credenciales, caemos en un Mock Feeder de demostración para Kalshi
        if not self.api_key_id or not self.private_key_path:
            print(
                f"[Feeder Kalshi] Credenciales no configuradas. Iniciando Feed Simulado para {self.symbol}..."
            )
            self.task = asyncio.create_task(self._run_mock_stream())
        else:
            print(
                f"[Feeder Kalshi] Iniciando conexión real con Kalshi WebSocket ({self.environment}) para {self.symbol}..."
            )
            self.task = asyncio.create_task(self._run_real_stream())

        while self.running:
            await asyncio.sleep(1)

    def stop(self):
        """Detiene el alimentador."""
        self.running = False
        if self.task:
            self.task.cancel()

    async def _run_mock_stream(self):
        """Genera fluctuaciones de precios simuladas de opciones binarias (entre 0.10 y 0.90 USD)."""
        price = 0.50  # Precio inicial (50%)
        while self.running:
            await asyncio.sleep(2.0)  # Emitir tick cada 2 segundos

            # Movimiento aleatorio (random walk)
            change = random.uniform(-0.03, 0.03)
            price = max(0.10, min(0.90, price + change))
            price = round(price, 2)

            # En Kalshi, el ask y el bid están muy pegados
            bid = round(max(0.01, price - 0.01), 2)
            ask = round(min(0.99, price + 0.01), 2)

            event = PriceUpdateEvent(symbol=self.symbol, price=price, ask=ask, bid=bid)

            await self.queue.put(event)

    async def _run_real_stream(self):
        """Establece conexión WebSocket con Kalshi y procesa cotizaciones reales (CLOB)."""
        import websockets

        # Para firmar la autenticación del WebSocket de Kalshi:
        # Se necesita firmar un timestamp y enviar la suscripción.
        # Por simplicidad y robustez, implementamos reconexiones automáticas.
        while self.running:
            try:
                async with websockets.connect(self.ws_url) as ws:
                    print("[Feeder Kalshi] Conectado al WebSocket de Kalshi.")

                    # Generar firma para autenticación si es requerido (Kalshi v2 exige login para streaming de libro privado,
                    # pero algunas cotizaciones de canales públicos se pueden suscribir sin login).
                    # Enviamos mensaje de suscripción para el ticker
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

                        # Manejar mensajes del canal de ticker
                        if (
                            msg.get("type") == "ticker"
                            and msg.get("market_key") == self.symbol
                        ):
                            # En Kalshi ticker, el precio de mercado es el midpoint o último trade
                            # Ejemplo de respuesta del WebSocket: msg.get("price") o msg.get("yes_bid") / msg.get("yes_ask")
                            # Convertimos precios que suelen estar expresados en centavos (ej: 54 para $0.54)
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
                print(
                    f"[Feeder Kalshi] Error en conexión WebSocket: {e}. Reintentando en 5 segundos..."
                )
                await asyncio.sleep(5)
