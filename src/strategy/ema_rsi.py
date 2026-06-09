import pandas as pd
from src.strategy.base import BaseStrategy
from src.events import PriceUpdateEvent, SignalEvent


class EmaRsiStrategy(BaseStrategy):
    def __init__(
        self, symbol: str, ema_short: int = 9, ema_long: int = 21, rsi_period: int = 14
    ):
        super().__init__(symbol)
        self.ema_short = ema_short
        self.ema_long = ema_long
        self.rsi_period = rsi_period

        # Guardar estado del último cruce para evitar señales repetidas
        self.last_position = None  # Puede ser 'BUY', 'SELL' o None

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
        """Evalúa las condiciones de cruce de EMA y rango de RSI."""
        min_samples = max(self.ema_long, self.rsi_period) + 2

        # Esperar a tener suficientes datos
        if len(self.prices_df) < min_samples:
            return None

        df = self.calculate_indicators()

        # Obtener los dos últimos registros para detectar cruces
        prev = df.iloc[-2]
        curr = df.iloc[-1]

        ema_short_prev, ema_long_prev = prev["ema_short"], prev["ema_long"]
        ema_short_curr, ema_long_curr = curr["ema_short"], curr["ema_long"]
        rsi_curr = curr["rsi"]

        # Se necesita un cruce hacia arriba (Compra)
        # EMA_corta cruza hacia arriba a EMA_larga
        crossover_up = (ema_short_prev <= ema_long_prev) and (
            ema_short_curr > ema_long_curr
        )

        # Se necesita un cruce hacia abajo (Venta)
        # EMA_corta cruza hacia abajo a EMA_larga
        crossover_down = (ema_short_prev >= ema_long_prev) and (
            ema_short_curr < ema_long_curr
        )

        # Condición del RSI para confirmación adaptada para capturar las ondas de simulación
        rsi_buy_valid = 40 <= rsi_curr < 85
        rsi_sell_valid = 15 < rsi_curr <= 60

        # Generar señales solo si cambia el estado de la posición
        if crossover_up and rsi_buy_valid and self.last_position != "BUY":
            self.last_position = "BUY"
            reason = f"Cruce alcista EMA {self.ema_short}/{self.ema_long} con RSI={rsi_curr:.2f}"
            return SignalEvent(self.symbol, "BUY", event.price, reason)

        elif crossover_down and rsi_sell_valid and self.last_position != "SELL":
            self.last_position = "SELL"
            reason = f"Cruce bajista EMA {self.ema_short}/{self.ema_long} con RSI={rsi_curr:.2f}"
            return SignalEvent(self.symbol, "SELL", event.price, reason)

        return None
