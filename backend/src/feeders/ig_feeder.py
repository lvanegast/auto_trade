import asyncio
import os
from trading_ig import IGService, IGStreamService
from lightstreamer.client import Subscription
from src.feeders.base import BaseFeeder
from src.events import PriceUpdateEvent


class PriceListener:
    def __init__(self, queue: asyncio.Queue, symbol: str, loop):
        self.queue = queue
        self.symbol = symbol
        self.loop = loop

    def onItemUpdate(self, item_update):
        """Callback invocado por Lightstreamer cuando hay cambio de precio."""
        try:
            # En IG, el precio bid y ask están en los campos 'BID' y 'OFFER' (o 'BIDPRICE1', 'ASKPRICE1')
            # Intentamos obtener ambos formatos
            bid_val = item_update.getValue("BID") or item_update.getValue("BIDPRICE1")
            ask_val = item_update.getValue("OFFER") or item_update.getValue("ASKPRICE1")

            if bid_val and ask_val:
                bid = float(bid_val)
                ask = float(ask_val)
                price = round((bid + ask) / 2.0, 5)

                # Crear evento
                event = PriceUpdateEvent(
                    symbol=self.symbol, price=price, ask=ask, bid=bid
                )

                # Insertar en la cola de forma segura desde el thread del WebSocket
                asyncio.run_coroutine_threadsafe(self.queue.put(event), self.loop)

        except Exception as e:
            print(f"[Feeder IG] Error procesando tick de precio: {e}")


class IGFeeder(BaseFeeder):
    def __init__(self, symbol: str, event_queue: asyncio.Queue):
        # Símbolo por defecto de EURUSD en IG si se ingresa EUR_USD o EURUSD
        # El epic estándar para EUR/USD hoy en IG es 'CS.D.EURUSD.TODAY.IP'
        formatted_symbol = symbol
        if symbol in ["EURUSD", "EUR_USD"]:
            formatted_symbol = "CS.D.EURUSD.TODAY.IP"
        elif symbol in ["GBPUSD", "GBP_USD"]:
            formatted_symbol = "CS.D.GBPUSD.TODAY.IP"

        super().__init__(formatted_symbol, event_queue)

        self.username = os.getenv("IG_USERNAME")
        self.password = os.getenv("IG_PASSWORD")
        self.api_key = os.getenv("IG_API_KEY")
        self.acc_number = os.getenv("IG_ACC_NUMBER")
        self.environment = os.getenv("IG_ENV", "DEMO").upper()  # 'DEMO' o 'LIVE'

    async def start(self):
        """Inicia el cliente IGService y el streaming de Lightstreamer con reconexión."""
        if not self.username or not self.password or not self.api_key:
            print(
                "[Feeder IG] ERROR: IG_USERNAME, IG_PASSWORD o IG_API_KEY faltan en el archivo .env"
            )
            return

        self.running = True
        print(f"[Feeder IG] Conectando a IG ({self.environment}) para {self.symbol}...")

        # Loop de reconexión con exponential backoff
        delay = 1.0
        while self.running:
            try:
                await asyncio.to_thread(self._connect_and_stream)
            except Exception as e:
                print(f"[Feeder IG] Fallo en la conexión/streaming de IG: {e}")

            if not self.running:
                break

            print(f"[Feeder IG] Reconectando en {delay:.1f}s...")
            await asyncio.sleep(delay)
            delay = min(delay * 2.0, 60.0)

    def _connect_and_stream(self):
        """Inicializa los servicios REST y Stream de IG."""
        # 1. Crear sesión REST principal
        self.ig_service = IGService(
            username=self.username,
            password=self.password,
            api_key=self.api_key,
            acc_type=self.environment,
            acc_number=self.acc_number,
        )

        # Iniciar sesión REST
        session = self.ig_service.create_session()
        if not session:
            print("[Feeder IG] ERROR: No se pudo autenticar la sesión con IG.")
            return

        print("[Feeder IG] Sesión REST autenticada con éxito.")

        # 2. Inicializar streaming asíncrono
        self.ig_stream_service = IGStreamService(self.ig_service)
        self.ig_stream_service.create_session()

        # 3. Definir suscripción
        # IG usa 'MARKET:{epic}' para streaming de cotizaciones
        price_subscription = Subscription(
            mode="MERGE",
            items=[f"MARKET:{self.symbol}"],
            fields=["BID", "OFFER", "HIGH", "LOW"],
        )

        # Obtener el event loop actual
        loop = asyncio.get_event_loop()

        # Añadir listener
        listener = PriceListener(self.queue, self.symbol, loop)
        price_subscription.addListener(listener)

        # 4. Suscribirse y arrancar
        self.ig_stream_service.subscribe(price_subscription)
        print(f"[Feeder IG] Suscripción activa para MARKET:{self.symbol}")

        # Mantener el hilo vivo mientras la bandera running sea True
        import time

        while self.running:
            time.sleep(0.5)  # Check rápido para shutdown ágil

        # Detener suscripciones si se apaga
        print("[Feeder IG] Cerrando conexiones de streaming...")
        try:
            self.ig_stream_service.disconnect()
        except Exception as e:
            print(f"[Feeder IG] Error al desconectar: {e}")
