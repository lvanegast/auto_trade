import logging
from src.core.security import security_guard

logger = logging.getLogger("risk_manager")


class RiskManager:
    """
    Gestor de Riesgo centralizado para el motor de trading.
    Aplica controles de Max Drawdown, Stop-Loss / Take-Profit y Kelly Sizing limits.
    """

    def __init__(self, db=None):
        self.db = db
        self.security_guard = security_guard

    def validate_trade_execution(self, worker_id: str) -> tuple[bool, str]:
        """Verifica si el trabajador tiene permiso para abrir nuevas posiciones."""
        return self.security_guard.can_trade(worker_id)

    def evaluate_stop_loss_take_profit(
        self,
        current_price: float,
        entry_price: float,
        side: str,
        stop_loss_pct: float = 0.0,
        take_profit_pct: float = 0.0,
    ) -> tuple[bool, str]:
        """
        Evalúa si la posición actual debe ser cerrada por Stop Loss o Take Profit.
        """
        if entry_price <= 0:
            return False, ""

        if side == "BUY":
            pnl_pct = (current_price - entry_price) / entry_price
        else:
            pnl_pct = (entry_price - current_price) / entry_price

        # Check Stop Loss
        if stop_loss_pct > 0 and pnl_pct <= -stop_loss_pct:
            return True, f"STOP_LOSS (-{abs(pnl_pct):.2%})"

        # Check Take Profit
        if take_profit_pct > 0 and pnl_pct >= take_profit_pct:
            return True, f"TAKE_PROFIT (+{pnl_pct:.2%})"

        return False, ""

    def record_pnl(self, worker_id: str, pnl: float):
        """Registra PnL en el guardián de seguridad para seguimiento de drawdown."""
        self.security_guard.record_pnl(worker_id, pnl)
