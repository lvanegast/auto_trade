"""
SecurityGuard — Global risk management for the trading bot.

Guards:
  1. Daily loss limit: stops all workers if cumulative P&L today < threshold
  2. Portfolio drawdown circuit breaker: stops all workers if equity drops X% from peak
  3. Max concurrent positions: prevents opening more than N positions at once
  4. Global rate limiter: max trades per minute across all workers
  5. Kill switch: emergency stop that flattens all positions and halts trading

All parameters are configurable via .env.
"""

import os
import time
import datetime
import logging

logger = logging.getLogger("security")


class SecurityGuard:
    def __init__(self, db=None):
        self.db = db

        # --- Config from env ---
        self.max_daily_loss_usd = float(os.getenv("MAX_DAILY_LOSS_USD", "50.0"))
        self.max_drawdown_pct = float(os.getenv("MAX_DRAWDOWN_PCT", "0.05"))
        self.max_concurrent_positions = int(os.getenv("MAX_CONCURRENT_POSITIONS", "3"))
        self.max_trades_per_minute = int(os.getenv("MAX_TRADES_PER_MINUTE", "20"))
        self.cooldown_after_loss_seconds = float(os.getenv("COOLDOWN_AFTER_LOSS_SECONDS", "30"))

        # --- State ---
        self._kill_switch = False
        self._kill_reason = ""
        self._paused_workers: set = set()
        self._trade_timestamps: list = []  # timestamps of recent trades (rate limiter)
        self._peak_equity = 0.0
        self._daily_pnl: dict[str, float] = {}  # {worker_id: cumulative P&L today}
        self._daily_reset_date: str = ""
        self._consecutive_losses: dict[str, int] = {}  # {worker_id: count}
        self._last_loss_time: dict[str, float] = {}  # {worker_id: monotonic time}
        self._halted = False
        self._halt_reason = ""

    # ------------------------------------------------------------------
    # Pre-trade checks: call these BEFORE executing any order
    # ------------------------------------------------------------------

    def can_trade(self, worker_id: str) -> tuple[bool, str]:
        """
        Master check: returns (allowed, reason).
        If False, the trade MUST be rejected.
        """
        # 0. Kill switch
        if self._kill_switch:
            return False, f"KILL SWITCH activo: {self._kill_reason}"

        # 0b. Global halt
        if self._halted:
            return False, f"Trading detenido: {self._halt_reason}"

        # 1. Worker paused after consecutive losses
        if worker_id in self._paused_workers:
            return False, f"Worker {worker_id} pausado por pérdidas consecutivas"

        # 2. Cooldown after loss
        last_loss = self._last_loss_time.get(worker_id, 0)
        if time.monotonic() - last_loss < self.cooldown_after_loss_seconds:
            remaining = self.cooldown_after_loss_seconds - (time.monotonic() - last_loss)
            return False, f"Cooldown post-pérdida: {remaining:.0f}s restantes"

        # 3. Rate limiter
        now = time.time()
        self._trade_timestamps = [t for t in self._trade_timestamps if now - t < 60]
        if len(self._trade_timestamps) >= self.max_trades_per_minute:
            return False, f"Límite de trades/minuto alcanzado ({self.max_trades_per_minute})"

        # 4. Max concurrent positions
        if self.db:
            open_positions = self.db.get_open_positions()
            if len(open_positions) >= self.max_concurrent_positions:
                return False, f"Máximo de posiciones simultáneas alcanzado ({self.max_concurrent_positions})"

        return True, "OK"

    def record_trade(self):
        """Call after a successful trade execution (for rate limiter)."""
        self._trade_timestamps.append(time.time())

    def record_pnl(self, worker_id: str, pnl: float):
        """
        Record P&L from a closed position.
        Triggers daily loss check and consecutive loss tracking.
        """
        self._ensure_daily_reset()

        self._daily_pnl[worker_id] = self._daily_pnl.get(worker_id, 0.0) + pnl

        # Track consecutive losses
        if pnl < 0:
            self._consecutive_losses[worker_id] = self._consecutive_losses.get(worker_id, 0) + 1
            self._last_loss_time[worker_id] = time.monotonic()

            if self._consecutive_losses[worker_id] >= 3:
                self._paused_workers.add(worker_id)
                logger.warning(
                    f"[SecurityGuard] Worker {worker_id} PAUSADO: "
                    f"{self._consecutive_losses[worker_id]} pérdidas consecutivas"
                )
                if self.db:
                    self.db.log(
                        "WARNING",
                        f"[SecurityGuard] Worker {worker_id} pausado: "
                        f"{self._consecutive_losses[worker_id]} pérdidas consecutivas",
                        worker_id,
                    )
        else:
            self._consecutive_losses[worker_id] = 0

        # Check daily loss limit
        total_daily = sum(self._daily_pnl.values())
        if total_daily < -self.max_daily_loss_usd:
            self._halt_all(
                f"Límite diario de pérdidas alcanzado: ${total_daily:.2f} "
                f"(límite: -${self.max_daily_loss_usd:.2f})"
            )

    def update_equity(self, total_equity: float):
        """
        Update peak equity and check drawdown circuit breaker.
        Call periodically with total portfolio equity across all workers.
        """
        if total_equity > self._peak_equity:
            self._peak_equity = total_equity

        if self._peak_equity > 0:
            drawdown = (self._peak_equity - total_equity) / self._peak_equity
            if drawdown >= self.max_drawdown_pct:
                self._halt_all(
                    f"Drawdown máximo alcanzado: {drawdown:.2%} desde pico "
                    f"(${self._peak_equity:.2f} → ${total_equity:.2f})"
                )

    # ------------------------------------------------------------------
    # Kill switch & halt
    # ------------------------------------------------------------------

    def trigger_kill_switch(self, reason: str = "Manual emergency stop"):
        """Emergency: immediately halts ALL trading."""
        self._kill_switch = True
        self._kill_reason = reason
        logger.critical(f"[SecurityGuard] KILL SWITCH ACTIVADO: {reason}")
        if self.db:
            self.db.log("CRITICAL", f"[SecurityGuard] KILL SWITCH: {reason}", "ALL")

    def release_kill_switch(self):
        """Release the kill switch (requires manual confirmation)."""
        self._kill_switch = False
        self._kill_reason = ""
        self._halted = False
        self._halt_reason = ""
        logger.info("[SecurityGuard] Kill switch liberado")
        if self.db:
            self.db.log("INFO", "[SecurityGuard] Kill switch liberado", "ALL")

    def unpause_worker(self, worker_id: str):
        """Manually unpause a worker that was auto-paused for losses."""
        self._paused_workers.discard(worker_id)
        self._consecutive_losses[worker_id] = 0
        logger.info(f"[SecurityGuard] Worker {worker_id} reanudado manualmente")

    def _halt_all(self, reason: str):
        """Internal: halt all trading (less severe than kill switch)."""
        if self._halted:
            return  # already halted
        self._halted = True
        self._halt_reason = reason
        logger.error(f"[SecurityGuard] TRADING DETENIDO: {reason}")
        if self.db:
            self.db.log("ERROR", f"[SecurityGuard] Trading detenido: {reason}", "ALL")

    # ------------------------------------------------------------------
    # Metrics (for API endpoint)
    # ------------------------------------------------------------------

    def get_metrics(self) -> dict:
        """Returns current risk metrics for the dashboard."""
        self._ensure_daily_reset()

        return {
            "kill_switch": self._kill_switch,
            "kill_reason": self._kill_reason,
            "halted": self._halted,
            "halt_reason": self._halt_reason,
            "paused_workers": list(self._paused_workers),
            "daily_pnl": dict(self._daily_pnl),
            "total_daily_pnl": sum(self._daily_pnl.values()),
            "max_daily_loss_usd": self.max_daily_loss_usd,
            "peak_equity": self._peak_equity,
            "max_drawdown_pct": self.max_drawdown_pct,
            "trades_last_minute": len(
                [t for t in self._trade_timestamps if time.time() - t < 60]
            ),
            "max_trades_per_minute": self.max_trades_per_minute,
            "consecutive_losses": dict(self._consecutive_losses),
            "concurrent_positions": len(self.db.get_open_positions()) if self.db else 0,
            "max_concurrent_positions": self.max_concurrent_positions,
        }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _ensure_daily_reset(self):
        """Reset daily P&L counters at midnight."""
        today = datetime.date.today().isoformat()
        if self._daily_reset_date != today:
            if self._daily_pnl:
                logger.info(
                    f"[SecurityGuard] Daily reset: yesterday P&L = "
                    f"${sum(self._daily_pnl.values()):.2f}"
                )
            self._daily_pnl = {}
            self._consecutive_losses = {}
            self._paused_workers = set()
            self._daily_reset_date = today

    def set_db(self, db):
        """Set DB reference after construction (allows lazy init)."""
        self.db = db


# Singleton
security_guard = SecurityGuard()
