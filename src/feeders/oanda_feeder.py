import asyncio
import json
import requests
import os
from src.feeders.base import BaseFeeder
from src.events import PriceUpdateEvent


class OandaFeeder(BaseFeeder):
    def __init__(self, symbol: str, event_queue: asyncio.Queue, interval: float = 1.0):
        # OANDA usa nomenclatura con guión bajo para pares, ej: EUR_USD, GBP_USD
        # Si recibimos EURUSD, lo formateamos a EUR_USD
        formatted_symbol = symbol
        if len(symbol) == 6 and "_" not in symbol:
            formatted_symbol = f"{symbol[:3]}_{symbol[3:]}"

        super().__init__(formatted_symbol, event_queue)

        self.account_id = os.getenv("OANDA_ACCOUNT_ID")
        self.token = os.getenv("OANDA_API_TOKEN")
        self.environment = os.getenv("OANDA_ENV", "practice")  # 'practice' o 'trade'

        # Determinar hosts según el entorno
        if self.environment == "trade":
            self.stream_host = "stream-fxtrade.oanda.com"
        else:
            self.stream_host = "stream-fxpractice.oanda.com"

    async def start(self):
        """Inicia el streaming de datos reales de OANDA."""
        if not self.account_id or not self.token:
            print(
                "[Feeder OANDA] ERROR: OANDA_ACCOUNT_ID u OANDA_API_TOKEN faltan en el archivo .env"
            )
            print(
                "[Feeder OANDA] Por favor obtén tus credenciales demo gratuitas en oanda.com"
            )
            return

        self.running = True
        print(
            f"[Feeder OANDA] Iniciando streaming real para {self.symbol} en entorno: {self.environment}"
        )

        # Ejecutar la función de streaming bloqueante en un hilo secundario asíncrono
        try:
            await asyncio.to_thread(self._stream_prices)
        except Exception as e:
            print(f"[Feeder OANDA] Error en streaming: {e}")
            self.running = False

    def _stream_prices(self):
        """Establece conexión persistente con OANDA y procesa los ticks."""
        url = f"https://{self.stream_host}/v3/accounts/{self.account_id}/pricing/stream"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }
        params = {"instruments": self.symbol}

        # Conexión persistente mediante stream=True
        with requests.get(
            url, headers=headers, params=params, stream=True, timeout=30
        ) as response:
            if response.status_code != 200:
                print(
                    f"[Feeder OANDA] Error al conectar. Status code: {response.status_code}"
                )
                print(f"[Feeder OANDA] Detalle: {response.text}")
                return

            for line in response.iter_lines():
                if not self.running:
                    break

                if line:
                    try:
                        data = json.loads(line.decode("utf-8"))

                        # Las líneas de OANDA contienen ticks de precio o latidos de red (heartbeats)
                        if data.get("type") == "PRICE":
                            instrument = data.get("instrument")
                            bids = data.get("bids", [])
                            asks = data.get("asks", [])

                            if bids and asks:
                                bid = float(bids[0]["price"])
                                ask = float(asks[0]["price"])
                                # El precio medio
                                current_price = round((bid + ask) / 2.0, 5)

                                # Empaquetar en nuestro evento unificado
                                event = PriceUpdateEvent(
                                    symbol=instrument,
                                    price=current_price,
                                    ask=ask,
                                    bid=bid,
                                )

                                # Insertar en la cola asíncrona usando la llamada síncrona segura del thread loop
                                loop = asyncio.get_event_loop()
                                asyncio.run_coroutine_threadsafe(
                                    self.queue.put(event), loop
                                )

                        elif data.get("type") == "HEARTBEAT":
                            # Mensaje de mantenimiento de conexión de OANDA, lo ignoramos para la estrategia
                            pass

                    except Exception as e:
                        print(f"[Feeder OANDA] Error procesando línea de stream: {e}")
