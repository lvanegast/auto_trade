from abc import ABC, abstractmethod
import pandas as pd
import os
from datetime import datetime
from src.events import PriceUpdateEvent, SignalEvent


class BaseStrategy(ABC):
    def __init__(self, symbol: str):
        self.symbol = symbol
        self.prices_df = pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "price"])

        # Cargar intervalo de agregación (por defecto 60 segundos)
        try:
            self.bar_interval = int(os.getenv("BAR_INTERVAL_SECONDS", "60"))
        except Exception:
            self.bar_interval = 60

    def on_price_update(self, event: PriceUpdateEvent) -> SignalEvent:
        """Agrega el precio al historial agrupando en barras y evalúa la señal en cierre de barra."""
        timestamp_s = event.timestamp.timestamp()
        rounded_s = (timestamp_s // self.bar_interval) * self.bar_interval
        # Mantener timezone si existe
        bar_time = datetime.fromtimestamp(rounded_s, tz=event.timestamp.tzinfo)

        signal = None

        if self.prices_df.empty:
            # Primera barra: la agregamos y no evaluamos señal (falta historial)
            new_row = pd.DataFrame([{
                "timestamp": bar_time,
                "open": event.price,
                "high": event.price,
                "low": event.price,
                "close": event.price,
                "price": event.price
            }])
            self.prices_df = pd.concat([self.prices_df, new_row], ignore_index=True)
        else:
            # Eliminar tzinfo para comparaciones limpias si es necesario (naive)
            if bar_time.tzinfo is not None:
                bar_time = bar_time.replace(tzinfo=None)

            last_idx = self.prices_df.index[-1]
            last_bar_time = self.prices_df.at[last_idx, "timestamp"]
            if hasattr(last_bar_time, "to_pydatetime"):
                last_bar_time = last_bar_time.to_pydatetime()
            if last_bar_time.tzinfo is not None:
                last_bar_time = last_bar_time.replace(tzinfo=None)

            if bar_time == last_bar_time:
                # Mismo intervalo: la barra sigue abierta.
                # Actualizamos el precio (este es el precio "en desarrollo" / open candle).
                self.prices_df.at[last_idx, "close"] = event.price
                self.prices_df.at[last_idx, "price"] = event.price
                if event.price > self.prices_df.at[last_idx, "high"]:
                    self.prices_df.at[last_idx, "high"] = event.price
                if event.price < self.prices_df.at[last_idx, "low"]:
                    self.prices_df.at[last_idx, "low"] = event.price
            elif bar_time > last_bar_time:
                # Ha comenzado una nueva barra!
                # La barra anterior (`last_bar_time`) se ha cerrado definitivamente.
                # Evaluamos la estrategia sobre el historial cerrado actual.
                signal = self.evaluate_signal(event)

                # Después de evaluar la señal en las barras cerradas, añadimos la nueva barra abierta:
                new_row = pd.DataFrame([{
                    "timestamp": bar_time,
                    "open": event.price,
                    "high": event.price,
                    "low": event.price,
                    "close": event.price,
                    "price": event.price
                }])
                self.prices_df = pd.concat([self.prices_df, new_row], ignore_index=True)

                # Limitar historial para no consumir memoria infinita
                if len(self.prices_df) > 1000:
                    self.prices_df = self.prices_df.iloc[-1000:].reset_index(drop=True)

        return signal

    @abstractmethod
    def evaluate_signal(self, event: PriceUpdateEvent) -> SignalEvent:
        """Lógica de la estrategia para decidir comprar o vender. Retorna SignalEvent o None."""
        pass
