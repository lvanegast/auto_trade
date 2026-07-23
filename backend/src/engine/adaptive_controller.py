"""
AdaptiveController — Bucle de Control de Retroalimentación (Closed-Loop Control System).

Monitorea la ventana de los últimos N trades de cada worker en la base de datos PostgreSQL
y ajusta en caliente los parámetros de trading (Min Net Edge, Tamaño de Posición de Kelly, Cooldown)
para maximizar la rentabilidad neta y mitigar drawdowns.
"""

import logging
import os
from typing import Dict, Any, Tuple

logger = logging.getLogger(__name__)


class AdaptiveController:
    def __init__(self, db_manager=None, lookback_trades: int = 20):
        self.db = db_manager
        self.lookback_trades = lookback_trades
        self.worker_params: Dict[str, Dict[str, Any]] = {}

    def evaluate_and_adjust_worker(self, worker_id: str, current_min_edge: float, current_pos_size: float) -> Tuple[float, float, str]:
        """
        Lee el historial reciente del worker desde DB, evalúa el rendimiento y ajusta parámetros.
        Retorna: (adjusted_min_edge, adjusted_pos_size, feedback_reason).
        """
        if not self.db:
            return current_min_edge, current_pos_size, "Sin conexión DB para feedback"

        try:
            # Obtener los últimos trades cerrados del worker
            trades = self.db.get_trades(worker_id=worker_id, limit=self.lookback_trades)
            if len(trades) < 5:
                return current_min_edge, current_pos_size, f"Insuficientes datos para feedback ({len(trades)}/5 trades)"

            wins = [t for t in trades if t.get("pnl", 0) > 0]
            losses = [t for t in trades if t.get("pnl", 0) < 0]
            win_rate = (len(wins) / len(trades)) * 100.0 if trades else 0.0

            total_pnl = sum(t.get("pnl", 0) for t in trades)
            gross_profit = sum(t.get("pnl", 0) for t in wins)
            gross_loss = abs(sum(t.get("pnl", 0) for t in losses))
            profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (gross_profit if gross_profit > 0 else 1.0)

            adj_edge = current_min_edge
            adj_pos_size = current_pos_size
            action_log = []

            # -------------------------------------------------------------
            # LÓGICA DE CONTROL POR RETROALIMENTACIÓN (FEEDBACK CONTROL LOOP)
            # -------------------------------------------------------------
            # Regla 1: Si el Profit Factor es excelente (> 2.0) y Win Rate > 85% -> Escalar posición (+15%)
            if profit_factor >= 2.0 and win_rate >= 85.0:
                max_pos = float(os.getenv("MAX_ADAPTIVE_POSITION_USD", "200.0"))
                adj_pos_size = min(max_pos, current_pos_size * 1.15)
                action_log.append(f"Performance Excelente (PF: {profit_factor:.2f}, WR: {win_rate:.1f}%) -> Escalar Posición a ${adj_pos_size:.2f}")

            # Regla 2: Si Win Rate cae por debajo de 60% o Profit Factor < 1.1 -> Subir exigencia de Edge (+0.5%) y reducir posición (-20%)
            elif win_rate < 60.0 or profit_factor < 1.1:
                adj_edge = min(0.08, current_min_edge + 0.005)
                min_pos = float(os.getenv("MIN_ADAPTIVE_POSITION_USD", "10.0"))
                adj_pos_size = max(min_pos, current_pos_size * 0.80)
                action_log.append(f"Rendimiento Degradado (PF: {profit_factor:.2f}, WR: {win_rate:.1f}%) -> Proteger Capital: Min Edge = {adj_edge:.2%}, Pos = ${adj_pos_size:.2f}")

            # Regla 3: Si Win Rate está estable (60% - 85%) -> Mantener equilibrio
            else:
                action_log.append(f"Rendimiento Estable (PF: {profit_factor:.2f}, WR: {win_rate:.1f}%) -> Parámetros estables")

            reason = " | ".join(action_log)
            logger.info(f"[AdaptiveController - {worker_id}] {reason}")
            
            # Guardar histórico de ajustes
            self.worker_params[worker_id] = {
                "min_edge": adj_edge,
                "position_size": adj_pos_size,
                "win_rate": win_rate,
                "profit_factor": profit_factor,
                "last_feedback_reason": reason
            }

            return round(adj_edge, 4), round(adj_pos_size, 2), reason

        except Exception as e:
            logger.error(f"[AdaptiveController Error] {e}")
            return current_min_edge, current_pos_size, f"Error en Feedback Loop: {e}"


adaptive_controller = AdaptiveController()
