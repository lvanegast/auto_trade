import asyncio
import json
import logging
import websockets
from src.strategy.base import BaseStrategy
from src.events import PriceUpdateEvent, SignalEvent

logger = logging.getLogger("LeadLagStrategy")


class BinanceTracker:
    """Clase estática compartida para almacenar cotizaciones en tiempo real de Binance."""

    latest_btc_price = 0.0
    latest_eth_price = 0.0
    is_listening = False


async def start_binance_websocket():
    """Inicia la conexión WebSocket con Binance para cotizaciones rápidas sin autenticación."""
    if BinanceTracker.is_listening:
        return
    BinanceTracker.is_listening = True

    url = "wss://stream.binance.com:9443/stream?streams=btcusdt@ticker/ethusdt@ticker"
    logger.info("Iniciando WebSocket de Binance Lead...")

    while BinanceTracker.is_listening:
        try:
            async with websockets.connect(
                url, ping_interval=20, ping_timeout=10
            ) as websocket:
                logger.info("Conectado con éxito al WebSocket de Binance Spot.")
                while BinanceTracker.is_listening:
                    message = await websocket.recv()
                    data = json.loads(message)
                    stream = data.get("stream", "")
                    ticker_data = data.get("data", {})

                    price = float(
                        ticker_data.get("c", 0.0)
                    )  # "c" es el precio actual de cierre

                    if "btcusdt" in stream:
                        BinanceTracker.latest_btc_price = price
                    elif "ethusdt" in stream:
                        BinanceTracker.latest_eth_price = price

        except Exception as e:
            logger.error(
                f"Error en WebSocket de Binance: {e}. Reintentando en 3 segundos..."
            )
            await asyncio.sleep(3)


class LeadLagArbitrageStrategy(BaseStrategy):
    def __init__(
        self,
        symbol: str,
        arbitrage_threshold: float = 0.0012,  # Umbral de desviación (0.12% o 12 bps)
        min_profit_target: float = 0.0020,  # Target de salida (0.20%)
        max_hold_seconds: float = 8.0,  # Tiempo máximo para mantener la posición
    ):
        super().__init__(symbol)
        self.arbitrage_threshold = arbitrage_threshold
        self.min_profit_target = min_profit_target
        self.max_hold_seconds = max_hold_seconds

        # Estado de la posición
        self.last_position = None  # 'BUY', 'SELL', None
        self.entry_price = 0.0
        self.entry_time = None
        self.entry_lead_price = 0.0

    @property
    def teorical_probability(self) -> float:
        if "BTC" in self.symbol:
            return BinanceTracker.latest_btc_price
        elif "ETH" in self.symbol:
            return BinanceTracker.latest_eth_price
        return BinanceTracker.latest_btc_price

    @property
    def edge(self) -> float:
        lead = self.teorical_probability
        if len(self.prices_df) > 0:
            current = self.prices_df.iloc[-1]["price"]
            if current > 0:
                return (lead - current) / current
        return 0.0

    @property
    def kelly_recommendation(self) -> float:
        return self.arbitrage_threshold

    def evaluate_signal(self, event: PriceUpdateEvent) -> SignalEvent:
        """Evaluación principal de la estrategia sobre barra cerrada (no usada en tick-a-tick)."""
        return None

    def on_price_update(self, event: PriceUpdateEvent) -> SignalEvent:
        """Sobrescribe la actualización de precio tick-a-tick para arbitraje de latencia."""
        # Asegurar que el listener de Binance esté corriendo
        if not BinanceTracker.is_listening:
            asyncio.create_task(start_binance_websocket())

        super().on_price_update(event)

        current_price = event.price
        # Determinar el precio del líder (Binance) para este símbolo
        lead_price = 0.0
        if "BTC" in self.symbol:
            lead_price = BinanceTracker.latest_btc_price
        elif "ETH" in self.symbol:
            lead_price = BinanceTracker.latest_eth_price
        else:
            # Para contratos de predicción vinculados a BTC/ETH por defecto
            lead_price = BinanceTracker.latest_btc_price

        # Si Binance aún no tiene cotizaciones cargadas, no operamos
        if lead_price <= 0.0:
            return None

        # Gestionar salida por tiempo o por beneficio si tenemos posición activa
        if self.last_position is not None:
            return self._evaluate_exit(current_price, lead_price)

        # Evaluar entrada
        # Desviación porcentual = (lead_price - current_price) / current_price
        deviation = (lead_price - current_price) / current_price

        # Caso 1: Binance se disparó arriba y el precio actual (Alpaca/Polymarket) se quedó atrás
        if deviation > self.arbitrage_threshold:
            self.last_position = "BUY"
            self.entry_price = current_price
            self.entry_lead_price = lead_price
            self.entry_time = asyncio.get_event_loop().time()

            logger.info(
                f"[Arbitraje] Entrada COMPRA en {self.symbol} a {current_price}. "
                f"Líder (Binance): {lead_price} (Desviación: {deviation:+.4%})"
            )

            return SignalEvent(
                symbol=self.symbol,
                side="BUY",
                price=current_price,
                reason=f"Arbitraje Lead-Lag: Binance lidera a {lead_price} (Desviación: {deviation:+.4%})",
                amount=1.0,  # Tamaño del trade por defecto
            )

        # Caso 2: Binance cayó fuerte y el precio local se quedó arriba (oportunidad de Venta/Corto)
        elif deviation < -self.arbitrage_threshold:
            self.last_position = "SELL"
            self.entry_price = current_price
            self.entry_lead_price = lead_price
            self.entry_time = asyncio.get_event_loop().time()

            logger.info(
                f"[Arbitraje] Entrada VENTA en {self.symbol} a {current_price}. "
                f"Líder (Binance): {lead_price} (Desviación: {deviation:+.4%})"
            )

            return SignalEvent(
                symbol=self.symbol,
                side="SELL",
                price=current_price,
                reason=f"Arbitraje Lead-Lag: Binance lidera a {lead_price} (Desviación: {deviation:+.4%})",
                amount=1.0,
            )

        return None

    def _evaluate_exit(self, current_price: float, lead_price: float) -> SignalEvent:
        """Determina si debemos cerrar la posición de arbitraje por límite de tiempo o beneficio."""
        now = asyncio.get_event_loop().time()
        elapsed = now - self.entry_time

        # Calcular retorno actual
        if self.last_position == "BUY":
            profit_pct = (current_price - self.entry_price) / self.entry_price
        else:
            profit_pct = (self.entry_price - current_price) / self.entry_price

        # Salida 1: Se alcanzó el profit target mínimo
        if profit_pct >= self.min_profit_target:
            side = "SELL" if self.last_position == "BUY" else "BUY"
            reason = f"Profit Target alcanzado: {profit_pct:+.2%} en {elapsed:.1f}s"
            return self._trigger_exit(side, current_price, reason)

        # Salida 2: Tiempo de mantenimiento máximo alcanzado (Time Stop)
        if elapsed >= self.max_hold_seconds:
            side = "SELL" if self.last_position == "BUY" else "BUY"
            reason = f"Time Stop alcanzado ({elapsed:.1f}s). Retorno: {profit_pct:+.2%}"
            return self._trigger_exit(side, current_price, reason)

        return None

    def _trigger_exit(self, side: str, price: float, reason: str) -> SignalEvent:
        self.last_position = None
        self.entry_price = 0.0
        self.entry_lead_price = 0.0
        self.entry_time = None

        logger.info(f"[Arbitraje] Cierre de posición: {reason}")
        return SignalEvent(
            symbol=self.symbol, side=side, price=price, reason=reason, amount=1.0
        )

    def calculate_indicators(self):
        """Calcula EMAs y RSI referenciales para la visualización del UI."""
        df = self.prices_df.copy()
        if len(df) < 2:
            df["ema_short"] = df["price"]
            df["ema_long"] = df["price"]
            df["rsi"] = 50.0
            return df

        df["ema_short"] = df["price"].ewm(span=9, adjust=False).mean()
        df["ema_long"] = df["price"].ewm(span=21, adjust=False).mean()

        delta = df["price"].diff()
        gain = (delta.where(delta > 0, 0)).ewm(alpha=1 / 14, adjust=False).mean()
        loss = (-delta.where(delta < 0, 0)).ewm(alpha=1 / 14, adjust=False).mean()
        rs = gain / loss.replace(0, 1e-9)
        df["rsi"] = 100 - (100 / (1 + rs))
        return df
