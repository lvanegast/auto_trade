import asyncio
import logging
import os
from src.strategy.base import BaseStrategy
from src.events import PriceUpdateEvent, SignalEvent
from src.feeders.connection_manager import AsyncWebSocketManager

logger = logging.getLogger("LeadLagStrategy")


class BinanceTracker:
    """Clase estática compartida para almacenar cotizaciones en tiempo real de Binance."""

    latest_btc_price: float = 0.0
    latest_eth_price: float = 0.0
    last_update_time: float = 0.0


class _BinanceWebSocketManager(AsyncWebSocketManager):
    """Gestor del WebSocket de Binance para el tracker de precios líder."""

    async def on_message(self, data: dict):
        import time as _time

        stream = data.get("stream", "")
        ticker_data = data.get("data", {})

        price = float(ticker_data.get("c", 0.0))

        if "btcusdt" in stream:
            BinanceTracker.latest_btc_price = price
            BinanceTracker.last_update_time = _time.monotonic()
        elif "ethusdt" in stream:
            BinanceTracker.latest_eth_price = price
            BinanceTracker.last_update_time = _time.monotonic()


# Singleton del WebSocket de Binance (compartido entre todos los workers)
_binance_ws_manager: _BinanceWebSocketManager | None = None
_binance_ws_lock = asyncio.Lock()


async def ensure_binance_websocket():
    """Asegura que el WebSocket de Binance esté corriendo (singleton, thread-safe)."""
    global _binance_ws_manager

    async with _binance_ws_lock:
        if _binance_ws_manager is not None and _binance_ws_manager._running:
            return

        if _binance_ws_manager is not None:
            logger.warning("BinanceTracker WebSocket no estaba activo. Reconectando...")
            try:
                await _binance_ws_manager.disconnect()
            except Exception:
                pass
            _binance_ws_manager = None

        url = (
            "wss://stream.binance.com:9443/stream?streams=btcusdt@ticker/ethusdt@ticker"
        )
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
        arbitrage_threshold: float = 0.0010,
        min_profit_target: float = 0.0015,
        max_hold_seconds: float = 15.0,
        stop_loss_pct: float = None,
        stop_loss_usd: float = None,
        trailing_stop_pct: float = None,
        cooldown_seconds: float = 5.0,
        position_size_pct: float = 0.15,
        db=None,
        worker_id: str = "worker_1",
    ):
        super().__init__(symbol)
        self.arbitrage_threshold = float(
            os.getenv("ARBITRAGE_THRESHOLD", str(arbitrage_threshold))
        )
        self.min_profit_target = float(
            os.getenv("TAKE_PROFIT_PCT", str(min_profit_target))
        )
        self.max_hold_seconds = float(
            os.getenv("MAX_HOLD_SECONDS", str(max_hold_seconds))
        )
        self.stop_loss_pct = float(
            os.getenv(
                "STOP_LOSS_PCT",
                str(stop_loss_pct if stop_loss_pct is not None else 0.005),
            )
        )
        self.stop_loss_usd = float(
            os.getenv(
                "STOP_LOSS_USD",
                str(stop_loss_usd if stop_loss_usd is not None else 15.0),
            )
        )
        self.trailing_stop_pct = float(
            os.getenv(
                "TRAILING_STOP_PCT",
                str(trailing_stop_pct if trailing_stop_pct is not None else 0.0010),
            )
        )
        self.cooldown_seconds = float(
            os.getenv("COOLDOWN_SECONDS", str(cooldown_seconds))
        )
        self.position_size_pct = float(
            os.getenv("POSITION_SIZE_PCT", str(position_size_pct))
        )

        self.db = db
        self.worker_id = worker_id
        self._position_id = None

        # Estado de la posición
        self.last_position = None
        self.entry_price = 0.0
        self.entry_time = None
        self.entry_lead_price = 0.0
        self._peak_profit = 0.0
        self._breakeven_activated = False
        self._last_exit_time = 0.0
        self._trade_count = 0
        self._win_count = 0

    @property
    def teorical_probability(self) -> float:
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
        return self.position_size_pct

    def evaluate_signal(self, event: PriceUpdateEvent) -> SignalEvent:
        return None

    def on_price_update(self, event: PriceUpdateEvent) -> SignalEvent:
        asyncio.create_task(ensure_binance_websocket())
        super().on_price_update(event)

        current_price = event.price
        lead_price = 0.0
        if "BTC" in self.symbol:
            lead_price = BinanceTracker.latest_btc_price
        elif "ETH" in self.symbol:
            lead_price = BinanceTracker.latest_eth_price
        else:
            lead_price = BinanceTracker.latest_btc_price

        if lead_price <= 0.0:
            return None

        if self.last_position is not None:
            return self._evaluate_exit(current_price, lead_price)

        now = asyncio.get_event_loop().time()

        # Cooldown: no entrar demasiado rápido después de un cierre
        if (
            self._last_exit_time > 0
            and (now - self._last_exit_time) < self.cooldown_seconds
        ):
            return None

        deviation = (lead_price - current_price) / current_price

        if deviation > self.arbitrage_threshold:
            return self._enter_position("BUY", current_price, lead_price, deviation)
        elif deviation < -self.arbitrage_threshold:
            return self._enter_position("SELL", current_price, lead_price, deviation)

        return None

    def _enter_position(
        self, side: str, current_price: float, lead_price: float, deviation: float
    ) -> SignalEvent:
        self.last_position = side
        self.entry_price = current_price
        self.entry_lead_price = lead_price
        self.entry_time = asyncio.get_event_loop().time()
        self._peak_profit = 0.0

        if self.db:
            self._position_id = self.db.save_position(
                self.worker_id,
                self.symbol,
                side,
                current_price,
                lead_price,
                amount=self.position_size_pct,
            )

        logger.info(
            f"[Arbitraje] Entrada {side} en {self.symbol} a {current_price}. "
            f"Líder (Binance): {lead_price} (Desviación: {deviation:+.4%})"
        )

        return SignalEvent(
            symbol=self.symbol,
            side=side,
            price=current_price,
            reason=f"Lead-Lag: Binance {lead_price} vs Local {current_price} (delta: {deviation:+.4%})",
            amount=self.position_size_pct,
            position_id=self._position_id,
        )

    def _evaluate_exit(self, current_price: float, lead_price: float) -> SignalEvent:
        now = asyncio.get_event_loop().time()
        elapsed = now - self.entry_time

        if self.last_position == "BUY":
            profit_pct = (current_price - self.entry_price) / self.entry_price
        else:
            profit_pct = (self.entry_price - current_price) / self.entry_price

        self._peak_profit = max(self._peak_profit, profit_pct)

        # USD-based P&L estimate (position_size_pct * entry_price * profit_pct * leverage)
        abs(profit_pct) * self.position_size_pct * self.entry_price

        # Breakeven trailing: when profit hits +0.10%, lock stop to entry price
        if not self._breakeven_activated and profit_pct >= self.min_profit_target * 0.5:
            self._breakeven_activated = True

        # Salida 1: Profit target
        if profit_pct >= self.min_profit_target:
            return self._trigger_exit(
                current_price, f"Profit Target: {profit_pct:+.2%} en {elapsed:.1f}s"
            )

        # Salida 2: Trailing stop (si el profit bajó X% desde el máximo)
        if (
            self.trailing_stop_pct > 0
            and self._peak_profit > self.min_profit_target * 0.5
        ):
            drawdown = self._peak_profit - profit_pct
            if drawdown >= self.trailing_stop_pct:
                return self._trigger_exit(
                    current_price,
                    f"Trailing Stop: pico {self._peak_profit:+.2%} -> actual {profit_pct:+.2%} (drawdown: {drawdown:.2%}) en {elapsed:.1f}s",
                )

        # Salida 3a: USD stop loss (hard cap)
        if self.stop_loss_usd > 0 and profit_pct < 0:
            loss_usd = abs(profit_pct) * self.position_size_pct * self.entry_price
            if loss_usd >= self.stop_loss_usd:
                return self._trigger_exit(
                    current_price, f"Stop Loss USD: -${loss_usd:.2f} en {elapsed:.1f}s"
                )

        # Salida 3b: Percentage stop loss (fallback)
        if self.stop_loss_pct > 0 and profit_pct <= -self.stop_loss_pct:
            return self._trigger_exit(
                current_price, f"Stop Loss: {profit_pct:+.2%} en {elapsed:.1f}s"
            )

        # Salida 4: Time stop
        if elapsed >= self.max_hold_seconds:
            return self._trigger_exit(
                current_price, f"Time Stop ({elapsed:.1f}s): {profit_pct:+.2%}"
            )

        return None

    def _trigger_exit(self, price: float, reason: str) -> SignalEvent:
        closed_position_id = self._position_id
        closing_side = "SELL" if self.last_position == "BUY" else "BUY"

        # Calculate P&L for security guard
        if self.last_position == "BUY":
            pnl = (price - self.entry_price) * self.position_size_pct
        elif self.last_position == "SELL":
            pnl = (self.entry_price - price) * self.position_size_pct
        else:
            pnl = 0.0

        if self._position_id and self.db:
            self.db.close_position(
                self._position_id, price, reason, worker_id=self.worker_id
            )

        # Record P&L in security guard
        from src.security import security_guard

        security_guard.record_pnl(self.worker_id, pnl)

        self._trade_count += 1
        if self.last_position == "BUY" and price > self.entry_price:
            self._win_count += 1
        elif self.last_position == "SELL" and price < self.entry_price:
            self._win_count += 1

        self._last_exit_time = asyncio.get_event_loop().time()
        self.last_position = None
        self.entry_price = 0.0
        self.entry_lead_price = 0.0
        self.entry_time = None
        self._position_id = None
        self._peak_profit = 0.0
        self._breakeven_activated = False

        logger.info(
            f"[Arbitraje] Cierre: {reason} | Win rate: {self._win_count}/{self._trade_count}"
        )

        return SignalEvent(
            symbol=self.symbol,
            side=closing_side,
            price=price,
            reason=reason,
            amount=self.position_size_pct,
            position_id=closed_position_id,
        )

    def calculate_indicators(self):
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
