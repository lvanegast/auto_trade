"""
auto_trade.strategy — Estrategias de trading algorítmico.

Cada estrategia implementa BaseStrategy y produce SignalEvent cuando detecta
condiciones de entrada/salida en el mercado.

Clases disponibles:
    BaseStrategy    — Clase abstracta. Acumula historial de precios en DataFrame
                      y orquesta la llamada a evaluate_signal().
    EmaRsiStrategy  — Estrategia EMA 9/21 + RSI 14 con suavizado de Wilder.
                      Señal BUY: cruce alcista EMA + RSI entre 40-85.
                      Señal SELL: cruce bajista EMA + RSI entre 15-60.
"""

from src.strategy.base import BaseStrategy
from src.strategy.ema_rsi import EmaRsiStrategy

__all__ = ["BaseStrategy", "EmaRsiStrategy"]
