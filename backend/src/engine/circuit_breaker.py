"""
CircuitBreaker — Fusible de Seguridad Financiera Global.

Monitorea las pérdidas diarias acumuladas en el portafolio de todos los workers.
Si la pérdida diaria alcanza o supera el umbral máximo permitido (MAX_DAILY_LOSS_PCT),
detiene inmediatamente la ejecución de todos los trabajadores y bloquea la emisión de nuevas órdenes.
"""

import logging
import os
from datetime import datetime
from typing import Tuple

logger = logging.getLogger(__name__)


class CircuitBreaker:
    def __init__(self, max_daily_loss_pct: float = 0.03):
        # Límite máximo de pérdida diaria (por defecto 3.0%)
        self.max_daily_loss_pct = float(os.getenv("MAX_DAILY_LOSS_PCT", str(max_daily_loss_pct)))
        self.is_tripped = False
        self.tripped_reason = ""
        self.tripped_timestamp = None
        self.starting_capital_day = 0.0

    def check_portfolio_safety(self, initial_capital: float, current_total_equity: float) -> Tuple[bool, str]:
        """
        Evalúa si la pérdida diaria acumulada ha superado el límite permitido.
        Retorna (safe_to_trade, reason).
        """
        if self.is_tripped:
            return False, f"CIRCUIT BREAKER ACTIVADO desde {self.tripped_timestamp}: {self.tripped_reason}"

        if initial_capital <= 0:
            return True, "Capital inicial no configurado"

        pnl_pct = (current_total_equity - initial_capital) / initial_capital

        # Verificar si la pérdida excede el límite (ej. -3.0%)
        if pnl_pct <= -self.max_daily_loss_pct:
            self.is_tripped = True
            self.tripped_reason = (
                f"Pérdida diaria acumulada ({pnl_pct:.2%}) superó el límite máximo de "
                f"-{self.max_daily_loss_pct:.2%}. Todos los workers detenidos automáticamente."
            )
            self.tripped_timestamp = datetime.now().isoformat()
            logger.critical(f"[CIRCUIT BREAKER] 🚨 FUSIBLE DISPARADO! {self.tripped_reason}")
            return False, self.tripped_reason

        return True, f"Portafolio Seguro | PnL Diario: {pnl_pct:+.2%} (Límite: -{self.max_daily_loss_pct:.2%})"

    def reset_circuit(self):
        """Restablece manualmente el fusible de seguridad."""
        self.is_tripped = False
        self.tripped_reason = ""
        self.tripped_timestamp = None
        logger.info("[CIRCUIT BREAKER] 🟢 Fusible restablecido manualmente.")


circuit_breaker = CircuitBreaker()
