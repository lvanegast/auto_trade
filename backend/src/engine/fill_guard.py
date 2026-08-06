"""
FillGuard — Prevención y recuperación de fill parcial para arbitraje 1×N.

Flujo:
1. PREVENCIÓN: Verificar saldo total (todas las patas + gas) antes de ejecutar
2. EJECUCIÓN: Enviar patas secuencialmente
3. RECUPERACIÓN: Si pata N falla, distinguir tipo de error:
   - Saldo insuficiente / validación → vender pata 1 inmediatamente
   - Timeout / error de red → reintentar con backoff (1s, 2s, 4s)
4. ALERTA: Registrar evento en DB para que el usuario lo vea
"""

import asyncio
import os
import time
from enum import Enum
from typing import List, Optional, Tuple
from dataclasses import dataclass


class ErrorCategory(Enum):
    """Categorías de error para decidir si reintentar o vender."""
    BALANCE = "balance"          # Saldo insuficiente, rechazo de validación
    NETWORK = "network"          # Timeout, conexión, error de red
    MARKET = "market"            # Mercado cerrado, liquidez insuficiente
    UNKNOWN = "unknown"          # Otros errores


@dataclass
class LegResult:
    """Resultado de la ejecución de una pata del arb."""
    signal: object
    success: bool
    error_category: Optional[ErrorCategory] = None
    error_message: str = ""
    order_id: Optional[str] = None


class FillGuard:
    """
    Gestiona la prevención y recuperación de fill parcial.
    
    Uso:
        guard = FillGuard(db, worker_id)
        
        # 1. Prevenir: verificar saldo antes de ejecutar
        can_proceed, reason = guard.validate_balance_for_arb(
            quote_balance, total_spend, gas_per_leg, num_legs
        )
        if not can_proceed:
            return  # No ejecutar ninguna pata
        
        # 2. Ejecutar con recuperación
        results = await guard.execute_arb_with_recovery(
            signals, execute_fn, sell_fn, quote_balance
        )
    """
    
    # Configuración de reintentos
    MAX_RETRIES = 3
    RETRY_BACKOFF = [1.0, 2.0, 4.0]  # segundos
    
    # Margen de seguridad para saldo (10%)
    BALANCE_MARGIN = 0.10
    
    def __init__(self, db, worker_id: str):
        self.db = db
        self.worker_id = worker_id
    
    def validate_balance_for_arb(
        self,
        quote_balance: float,
        total_spend: float,
        gas_per_leg: float = 0.005,
        num_legs: int = 2,
    ) -> Tuple[bool, str]:
        """
        Verifica que el saldo cubra TODAS las patas + gas + margen.
        
        Returns:
            (can_proceed, reason)
        """
        total_gas = gas_per_leg * num_legs
        required = total_spend + total_gas
        required_with_margin = required * (1.0 + self.BALANCE_MARGIN)
        
        if quote_balance < required_with_margin:
            reason = (
                f"Saldo insuficiente para arb completo: "
                f"disponible=${quote_balance:.4f}, "
                f"requerido=${required_with_margin:.4f} "
                f"(pata1+2=${total_spend:.4f} + gas=${total_gas:.4f} + margen={self.BALANCE_MARGIN:.0%})"
            )
            self.db.log("WARNING", f"[FillGuard] {reason}", self.worker_id)
            return False, reason
        
        return True, "OK"
    
    def classify_error(self, error: Exception) -> ErrorCategory:
        """
        Clasifica un error en categorías para decidir estrategia de recuperación.
        """
        error_str = str(error).lower()
        error_type = type(error).__name__.lower()
        
        # Errores de saldo / validación → NO reintentar
        balance_keywords = [
            "insufficient", "balance", "fondos", "saldo",
            "allowance", "approval", "rejected", "invalid",
            "validation", "bad request", "400", "422",
        ]
        if any(kw in error_str for kw in balance_keywords):
            return ErrorCategory.BALANCE
        
        # Errores de red / timeout → REINTENTAR
        network_keywords = [
            "timeout", "connection", "network", "refused",
            "unreachable", "reset", "eof", "ssl", "dns",
            "502", "503", "504", "429",
        ]
        if any(kw in error_str for kw in network_keywords):
            return ErrorCategory.NETWORK
        
        # Errores de mercado → NO reintentar
        market_keywords = [
            "closed", "expired", "locked", "resolved",
            "liquidity", "empty book",
        ]
        if any(kw in error_str for kw in market_keywords):
            return ErrorCategory.MARKET
        
        return ErrorCategory.UNKNOWN
    
    async def execute_arb_with_recovery(
        self,
        signals: list,
        execute_fn,
        sell_fn,
        quote_balance: float,
    ) -> List[LegResult]:
        """
        Ejecuta un arb 1×N con recuperación diferenciada por tipo de error.
        
        Args:
            signals: Lista de SignalEvent (ordenadas: pata 1, pata 2, ...)
            execute_fn: async fn(signal) -> (success, error, order_id)
            sell_fn: async fn(signal) -> bool  # Vende la posición
            quote_balance: Saldo disponible actual
        
        Returns:
            Lista de LegResult por cada pata
        """
        results = []
        filled_legs = []  # Patas que se llenaron exitosamente
        
        for i, signal in enumerate(signals):
            # Ejecutar pata
            success, error, order_id = await execute_fn(signal)
            
            if success:
                results.append(LegResult(
                    signal=signal,
                    success=True,
                    order_id=order_id,
                ))
                filled_legs.append(signal)
                self.db.log(
                    "INFO",
                    f"[FillGuard] Pata {i+1}/{len(signals)} OK: {signal.symbol}",
                    self.worker_id,
                )
                continue
            
            # Pata falló — clasificar error
            category = self.classify_error(error)
            result = LegResult(
                signal=signal,
                success=False,
                error_category=category,
                error_message=str(error),
            )
            
            if category == ErrorCategory.BALANCE or category == ErrorCategory.MARKET:
                # NO reintentar — vender patas llenadas inmediatamente
                self.db.log(
                    "ERROR",
                    f"[FillGuard] Pata {i+1}/{len(signals)} FALLÓ ({category.value}): {error}. "
                    f"Vendiendo {len(filled_legs)} patas llenadas inmediatamente.",
                    self.worker_id,
                )
                result.error_category = category
                results.append(result)
                
                # Vender todas las patas llenadas
                await self._emergency_sell(filled_legs, sell_fn, f"fill_partial_{category.value}")
                break
            
            elif category == ErrorCategory.NETWORK:
                # REINTENTAR con backoff
                self.db.log(
                    "WARNING",
                    f"[FillGuard] Pata {i+1}/{len(signals)} FALLÓ (network): {error}. "
                    f"Reintentando hasta {self.MAX_RETRIES} veces...",
                    self.worker_id,
                )
                
                retry_success = await self._retry_with_backoff(
                    signal, execute_fn, i+1, len(signals)
                )
                
                if retry_success:
                    results.append(LegResult(
                        signal=signal,
                        success=True,
                        order_id=order_id,
                    ))
                    filled_legs.append(signal)
                else:
                    # Reintentos agotados — vender patas llenadas
                    self.db.log(
                        "ERROR",
                        f"[FillGuard] Pata {i+1}/{len(signals)} FALLÓ después de "
                        f"{self.MAX_RETRIES} reintentos. Vendiendo {len(filled_legs)} patas.",
                        self.worker_id,
                    )
                    results.append(result)
                    await self._emergency_sell(filled_legs, sell_fn, "retries_exhausted")
                    break
            
            else:
                # UNKNOWN — vender por seguridad
                self.db.log(
                    "ERROR",
                    f"[FillGuard] Pata {i+1}/{len(signals)} FALLÓ (unknown): {error}. "
                    f"Vendiendo {len(filled_legs)} patas por seguridad.",
                    self.worker_id,
                )
                results.append(result)
                await self._emergency_sell(filled_legs, sell_fn, "unknown_error")
                break
        
        return results
    
    async def _retry_with_backoff(
        self,
        signal,
        execute_fn,
        leg_num: int,
        total_legs: int,
    ) -> bool:
        """
        Reintenta ejecutar una pata con backoff exponencial.
        
        Returns:
            True si algún reintento fue exitoso
        """
        for attempt in range(self.MAX_RETRIES):
            delay = self.RETRY_BACKOFF[attempt]
            
            self.db.log(
                "INFO",
                f"[FillGuard] Reintento {attempt+1}/{self.MAX_RETRIES} para pata {leg_num} "
                f"(esperando {delay}s)...",
                self.worker_id,
            )
            
            await asyncio.sleep(delay)
            
            success, error, order_id = await execute_fn(signal)
            
            if success:
                self.db.log(
                    "INFO",
                    f"[FillGuard] Reintento {attempt+1} exitoso para pata {leg_num}",
                    self.worker_id,
                )
                return True
            
            # Si el error cambió a balance/market, no seguir reintentando
            category = self.classify_error(error)
            if category in (ErrorCategory.BALANCE, ErrorCategory.MARKET):
                self.db.log(
                    "WARNING",
                    f"[FillGuard] Reintento {attempt+1} falló con error {category.value}: {error}. "
                    f"Dejando de reintentar.",
                    self.worker_id,
                )
                return False
        
        return False
    
    async def _emergency_sell(
        self,
        filled_legs: list,
        sell_fn,
        reason: str,
    ):
        """
        Vende todas las patas llenadas para salir de la exposición direccional.
        """
        if not filled_legs:
            return
        
        self.db.log(
            "CRITICAL",
            f"[FillGuard] EMERGENCY SELL: Vendiendo {len(filled_legs)} patas. "
            f"Razón: {reason}",
            self.worker_id,
        )
        
        for leg in filled_legs:
            try:
                # Crear señal de venta
                from src.events import SignalEvent
                sell_signal = SignalEvent(
                    symbol=leg.symbol,
                    side="SELL",
                    price=leg.price,  # Se usará market order
                    reason=f"Emergency sell: {reason}",
                    amount=leg.amount if hasattr(leg, 'amount') else None,
                    position_size_usd=getattr(leg, 'position_size_usd', None),
                )
                
                success = await sell_fn(sell_signal)
                
                if success:
                    self.db.log(
                        "INFO",
                        f"[FillGuard] Emergency sell OK: {leg.symbol}",
                        self.worker_id,
                    )
                else:
                    self.db.log(
                        "CRITICAL",
                        f"[FillGuard] Emergency sell FALLÓ: {leg.symbol}. "
                        f"Posición expuesta sin cobertura.",
                        self.worker_id,
                    )
            except Exception as e:
                self.db.log(
                    "CRITICAL",
                    f"[FillGuard] Emergency sell ERROR: {leg.symbol}: {e}. "
                    f"Posición expuesta sin cobertura.",
                    self.worker_id,
                )


# Instancia global
_fill_guard: Optional[FillGuard] = None


def get_fill_guard(db=None, worker_id: str = None) -> FillGuard:
    """Obtiene o crea la instancia global de FillGuard."""
    global _fill_guard
    if _fill_guard is None and db is not None:
        _fill_guard = FillGuard(db, worker_id)
    return _fill_guard
