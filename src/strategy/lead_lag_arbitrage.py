import asyncio
import logging
from src.strategy.base import BaseStrategy
from src.events import PriceUpdateEvent, SignalEvent
from src.feeders.connection_manager import AsyncWebSocketManager

logger = logging.getLogger("LeadLagStrategy")


class BinanceTracker:
    """Clase estática compartida para almacenar cotizaciones en tiempo real de Binance."""

    latest_btc_price: float = 0.0
    latest_eth_price: float = 0.0


class _BinanceWebSocketManager(AsyncWebSocketManager):
    """Gestor del WebSocket de Binance para el tracker de precios líder."""

    async def on_message(self, data: dict):
        stream = data.get("stream", "")
        ticker_data = data.get("data", {})

        price = float(ticker_data.get("c", 0.0))

        if "btcusdt" in stream:
            BinanceTracker.latest_btc_price = price
        elif "ethusdt" in stream:
            BinanceTracker.latest_eth_price = price


# Singleton del WebSocket de Binance (compartido entre todos los workers)
_binance_ws_manager: _BinanceWebSocketManager | None = None
_binance_ws_lock = asyncio.Lock()


async def ensure_binance_websocket():
    """Asegura que el WebSocket de Binance esté corriendo (singleton, thread-safe)."""
    global _binance_ws_manager

    async with _binance_ws_lock:
        if _binance_ws_manager is not None:
            return

        url = "wss://stream.binance.com:9443/stream?streams=btcusdt@ticker/ethusdt@ticker"
        _binance_ws_manager = _BinanceWebSocketManager(
            url=url,
            ping_interval=20,
            ping_timeout=10,
            health_check_timeout=30.0,
            name="BinanceTracker",
        )
        await _binance_ws_manager.connect()
        logger.info("BinanceTracker WebSocket iniciado (singleton).")


class LeadLagArbitrageStrategy(BaseStrategy):
    def __init__(
        self,
        symbol: str,
        arbitrage_threshold: float = 0.0012,  # Umbral de desviación (0.12% o 12 bps)
        min_profit_target: float = 0.0020,  # Target de salida (0.20%)
        max_hold_seconds: float = 8.0,  # Tiempo máximo para mantener la posición
        stop_loss_pct: float = None,  # Stop loss porcentual (None = desactivado)
        db=None,
        worker_id: str = "worker_1",
    ):
        super().__init__(symbol)
        self.arbitrage_threshold = arbitrage_threshold
        self.min_profit_target = min_profit_target
        self.max_hold_seconds = max_hold_seconds
        self.stop_loss_pct = stop_loss_pct if stop_loss_pct is not None else float(
            __import__("os").getenv("STOP_LOSS_PCT", "0.0")
        )
        self.min_profit_target = min_profit_target if min_profit_target != 0.0020 else float(
            __import__("os").getenv("TAKE_PROFIT_PCT", str(min_profit_target))
        )
        self.db = db
        self.worker_id = worker_id
        self._position_id = None  # ID de la posición en DB

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
        
        # Para mercados de predicción, la probabilidad es el precio del contrato (0.0 - 1.0)
        if len(self.prices_df) > 0:
            return float(self.prices_df.iloc[-1]["price"])
        return 0.50

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
        # Asegurar que el listener de Binance esté corriendo (idempotente gracias al lock)
        asyncio.create_task(ensure_binance_websocket())

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

            # Persistir posición en DB
            if self.db:
                self._position_id = self.db.save_position(
                    self.worker_id, self.symbol, "BUY", current_price, lead_price
                )

            logger.info(
                f"[Arbitraje] Entrada COMPRA en {self.symbol} a {current_price}. "
                f"Líder (Binance): {lead_price} (Desviación: {deviation:+.4%})"
            )

            return SignalEvent(
                symbol=self.symbol,
                side="BUY",
                price=current_price,
                reason=f"Arbitraje Lead-Lag: Binance lidera a {lead_price} (Desviación: {deviation:+.4%})",
                amount=1.0,
                position_id=self._position_id,
            )

        # Caso 2: Binance cayó fuerte y el precio local se quedó arriba (oportunidad de Venta/Corto)
        elif deviation < -self.arbitrage_threshold:
            self.last_position = "SELL"
            self.entry_price = current_price
            self.entry_lead_price = lead_price
            self.entry_time = asyncio.get_event_loop().time()

            # Persistir posición en DB
            if self.db:
                self._position_id = self.db.save_position(
                    self.worker_id, self.symbol, "SELL", current_price, lead_price
                )

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
                position_id=self._position_id,
            )

        return None

    def _evaluate_exit(self, current_price: float, lead_price: float) -> SignalEvent:
        """Determina si debemos cerrar la posición de arbitraje por límite de tiempo, beneficio o stop-loss."""
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

        # Salida 2: Stop Loss alcanzado
        if self.stop_loss_pct > 0 and profit_pct <= -self.stop_loss_pct:
            side = "SELL" if self.last_position == "BUY" else "BUY"
            reason = f"Stop Loss alcanzado: {profit_pct:+.2%} (umbral: -{self.stop_loss_pct:.2%}) en {elapsed:.1f}s"
            return self._trigger_exit(side, current_price, reason)

        # Salida 3: Tiempo de mantenimiento máximo alcanzado (Time Stop)
        if elapsed >= self.max_hold_seconds:
            side = "SELL" if self.last_position == "BUY" else "BUY"
            reason = f"Time Stop alcanzado ({elapsed:.1f}s). Retorno: {profit_pct:+.2%}"
            return self._trigger_exit(side, current_price, reason)

        return None

    def _trigger_exit(self, side: str, price: float, reason: str) -> SignalEvent:
        # Cerrar posición en DB si existe
        closed_position_id = self._position_id
        if self._position_id and self.db:
            self.db.close_position(
                self._position_id, price, reason, worker_id=self.worker_id
            )

        self.last_position = None
        self.entry_price = 0.0
        self.entry_lead_price = 0.0
        self.entry_time = None
        self._position_id = None

        logger.info(f"[Arbitraje] Cierre de posición: {reason}")
        return SignalEvent(
            symbol=self.symbol, side=side, price=price, reason=reason, amount=1.0,
            position_id=closed_position_id,
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
