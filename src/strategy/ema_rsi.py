import pandas as pd
from src.strategy.base import BaseStrategy
from src.events import PriceUpdateEvent, SignalEvent


class EmaRsiStrategy(BaseStrategy):
    def __init__(
        self,
        symbol: str,
        ema_short: int = 9,
        ema_long: int = 21,
        rsi_period: int = 14,
        take_profit: float = 0.12,
        stop_loss: float = 0.06,
        trailing_stop: float = 0.04,
    ):
        super().__init__(symbol)
        self.ema_short = ema_short
        self.ema_long = ema_long
        self.rsi_period = rsi_period
        self.take_profit = take_profit
        self.stop_loss = stop_loss
        self.trailing_stop = trailing_stop

        # Guardar estado del último cruce y gestión de riesgo activa
        self.last_position = None  # Puede ser 'BUY', 'SELL' o None
        self.entry_price = None
        self.highest_price = None

    def calculate_indicators(self) -> pd.DataFrame:
        """Calcula EMAs y RSI a partir del historial de precios usando el suavizado de Wilder."""
        df = self.prices_df.copy()

        # Calcular Medias Móviles Exponenciales (EMA)
        df["ema_short"] = df["price"].ewm(span=self.ema_short, adjust=False).mean()
        df["ema_long"] = df["price"].ewm(span=self.ema_long, adjust=False).mean()

        # Calcular Índice de Fuerza Relativa (RSI) con suavizado de Wilder (EWM con alpha = 1/periodo)
        delta = df["price"].diff()
        gain = (
            (delta.where(delta > 0, 0))
            .ewm(alpha=1 / self.rsi_period, adjust=False)
            .mean()
        )
        loss = (
            (-delta.where(delta < 0, 0))
            .ewm(alpha=1 / self.rsi_period, adjust=False)
            .mean()
        )

        # Evitar división por cero
        rs = gain / loss.replace(0, 1e-9)
        df["rsi"] = 100 - (100 / (1 + rs))

        return df

    def evaluate_signal(self, event: PriceUpdateEvent) -> SignalEvent:
        """Evalúa las condiciones de cruce de EMA, RSI y límites de riesgo (TP/SL/TS)."""
        min_samples = max(self.ema_long, self.rsi_period) + 2

        # Esperar a tener suficientes datos
        if len(self.prices_df) < min_samples:
            return None

        # --- GESTIÓN DE RIESGO ACTIVA ---
        if self.last_position == "BUY" and self.entry_price is not None:
            current_price = event.price
            is_event = current_price < 1.5

            if self.highest_price is None or current_price > self.highest_price:
                self.highest_price = current_price

            # Evaluar activadores de salida
            if is_event:
                # Contratos de Eventos (Diferencia absoluta)
                tp_triggered = (current_price - self.entry_price) >= self.take_profit
                sl_triggered = (self.entry_price - current_price) >= self.stop_loss
                ts_triggered = (
                    self.highest_price - current_price
                ) >= self.trailing_stop
            else:
                # Criptomonedas / Activos tradicionales (Variación porcentual)
                tp_triggered = (
                    current_price - self.entry_price
                ) / self.entry_price >= self.take_profit
                sl_triggered = (
                    self.entry_price - current_price
                ) / self.entry_price >= self.stop_loss
                ts_triggered = (
                    self.highest_price - current_price
                ) / self.highest_price >= self.trailing_stop

            if tp_triggered:
                old_entry = self.entry_price
                self.last_position = "SELL"
                self.entry_price = None
                self.highest_price = None
                reason = f"Take Profit alcanzado a ${current_price:.4f} (Entrada: ${old_entry:.4f})"
                return SignalEvent(self.symbol, "SELL", current_price, reason)

            if sl_triggered:
                old_entry = self.entry_price
                self.last_position = "SELL"
                self.entry_price = None
                self.highest_price = None
                reason = f"Stop Loss alcanzado a ${current_price:.4f} (Entrada: ${old_entry:.4f})"
                return SignalEvent(self.symbol, "SELL", current_price, reason)

            if ts_triggered:
                old_entry = self.entry_price
                self.last_position = "SELL"
                self.entry_price = None
                self.highest_price = None
                reason = f"Trailing Stop alcanzado a ${current_price:.4f} (Entrada: ${old_entry:.4f}, Máximo: ${self.highest_price:.4f})"
                return SignalEvent(self.symbol, "SELL", current_price, reason)

        # --- ANÁLISIS TÉCNICO DE SEÑAL ---
        df = self.calculate_indicators()

        # Obtener los dos últimos registros para detectar cruces
        prev = df.iloc[-2]
        curr = df.iloc[-1]

        ema_short_prev, ema_long_prev = prev["ema_short"], prev["ema_long"]
        ema_short_curr, ema_long_curr = curr["ema_short"], curr["ema_long"]
        rsi_curr = curr["rsi"]

        # Se necesita un cruce hacia arriba (Compra)
        crossover_up = (ema_short_prev <= ema_long_prev) and (
            ema_short_curr > ema_long_curr
        )

        # Se necesita un cruce hacia abajo (Venta)
        crossover_down = (ema_short_prev >= ema_long_prev) and (
            ema_short_curr < ema_long_curr
        )

        # Rango del RSI para confirmación
        rsi_buy_valid = 40 <= rsi_curr < 85
        rsi_sell_valid = 15 < rsi_curr <= 60

        # Generar señales
        if crossover_up and rsi_buy_valid and self.last_position != "BUY":
            self.last_position = "BUY"
            self.entry_price = curr["price"]
            self.highest_price = curr["price"]
            reason = f"Cruce alcista EMA {self.ema_short}/{self.ema_long} con RSI={rsi_curr:.2f}"
            return SignalEvent(self.symbol, "BUY", event.price, reason)

        elif crossover_down and rsi_sell_valid and self.last_position != "SELL":
            self.last_position = "SELL"
            self.entry_price = None
            self.highest_price = None
            reason = f"Cruce bajista EMA {self.ema_short}/{self.ema_long} con RSI={rsi_curr:.2f}"
            return SignalEvent(self.symbol, "SELL", event.price, reason)

        return None
