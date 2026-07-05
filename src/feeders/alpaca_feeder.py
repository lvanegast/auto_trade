import asyncio
import os
from alpaca.data.live.crypto import CryptoDataStream
from alpaca.data.live.stock import StockDataStream
from src.feeders.base import BaseFeeder
from src.events import PriceUpdateEvent


class AlpacaFeeder(BaseFeeder):
    def __init__(self, symbol: str, event_queue: asyncio.Queue):
        # En Alpaca, las cripto usan formato BTC/USD y las acciones usan AAPL
        # Si el símbolo es tipo BTCUSDT o BTCUSD, lo formateamos con barra
        self.symbol_raw = symbol.upper()
        self.is_crypto = self._check_is_crypto()

        formatted_symbol = self.symbol_raw
        if self.is_crypto:
            # Convertir BTCUSDT -> BTC/USDT o BTCUSD -> BTC/USD
            if "/" not in formatted_symbol:
                if formatted_symbol.endswith("USDT"):
                    formatted_symbol = f"{formatted_symbol[:-4]}/USDT"
                elif formatted_symbol.endswith("USD"):
                    formatted_symbol = f"{formatted_symbol[:-3]}/USD"
                else:
                    # Fallback general
                    formatted_symbol = f"{formatted_symbol[:3]}/{formatted_symbol[3:]}"

        super().__init__(formatted_symbol, event_queue)

        self.api_key = os.getenv("ALPACA_API_KEY")
        self.secret_key = os.getenv("ALPACA_SECRET_KEY")

        self.stream = None
        self.task = None

    def _check_is_crypto(self) -> bool:
        """Determina si el símbolo es una criptomoneda."""
        crypto_keywords = [
            "BTC",
            "ETH",
            "SOL",
            "LTC",
            "XRP",
            "ADA",
            "DOT",
            "DOGE",
            "USDT",
            "USDC",
        ]
        # Si el símbolo contiene alguna de estas palabras, asumimos que es cripto
        return any(kw in self.symbol_raw for kw in crypto_keywords)

    async def start(self):
        """Inicia el streaming asíncrono desde Alpaca."""
        if not self.api_key or not self.secret_key or "your_alpaca" in self.api_key:
            print(
                "[Feeder Alpaca] ERROR: ALPACA_API_KEY o ALPACA_SECRET_KEY no están configuradas en el archivo .env"
            )
            return

        self.running = True

        if self.is_crypto:
            print(
                f"[Feeder Alpaca] Iniciando streaming de Criptomonedas para {self.symbol}..."
            )
            self.stream = CryptoDataStream(self.api_key, self.secret_key)
            self.stream.subscribe_quotes(self._handle_quote, self.symbol)
        else:
            print(
                f"[Feeder Alpaca] Iniciando streaming de Acciones para {self.symbol}..."
            )
            self.stream = StockDataStream(self.api_key, self.secret_key)
            self.stream.subscribe_quotes(self._handle_quote, self.symbol)

        # Iniciar el stream con watchdog: si la tarea muere, se reinicia automáticamente
        self._start_stream_task()

        # Mantener activo mientras self.running sea True, con watchdog
        while self.running:
            await asyncio.sleep(1)
            # Verificar si la tarea del stream murió inesperadamente
            if self.task and self.task.done():
                exc = self.task.exception()
                if exc:
                    print(
                        f"[Feeder Alpaca] ERROR: Tarea del stream terminó con excepción: {exc}"
                    )
                else:
                    print(
                        "[Feeder Alpaca] WARNING: Tarea del stream terminó inesperadamente."
                    )
                if self.running:
                    print("[Feeder Alpaca] Reiniciando tarea del stream...")
                    self._start_stream_task()

    def _start_stream_task(self):
        """Crea (o recrea) la tarea del stream con monitoreo."""
        if self.task and not self.task.done():
            self.task.cancel()
        self.task = asyncio.create_task(self.stream._run_forever())

    async def _handle_quote(self, quote):
        """Callback para procesar los quotes de Alpaca."""
        try:
            # En alpaca-py, las cotizaciones tienen bid_price y ask_price
            bid = float(quote.bid_price)
            ask = float(quote.ask_price)

            # El precio medio
            price = round((bid + ask) / 2.0, 5)

            event = PriceUpdateEvent(symbol=self.symbol, price=price, ask=ask, bid=bid)

            # Meter a la cola
            await self.queue.put(event)

        except Exception as e:
            print(f"[Feeder Alpaca] Error al procesar quote: {e}")

    async def stop(self):
        """Detiene el streaming de forma segura, esperando la limpieza del WebSocket."""
        self.running = False
        if self.stream:
            try:
                await self.stream.stop_ws()
                print(f"[Feeder Alpaca] WebSocket detenido correctamente para {self.symbol}.")
            except Exception as e:
                print(f"[Feeder Alpaca] Error al detener websocket: {e}")
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
            self.task = None
