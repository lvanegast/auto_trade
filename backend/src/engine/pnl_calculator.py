"""
PnLCalculator — calcula P&L real por canasta de arbitraje.

Flujo:
1. Agrupa posiciones por position_id (canasta completa)
2. Calcula costo total de todas las patas
3. Calcula revenue de la pata ganadora ($1.00 × shares)
4. P&L = revenue - costo_total
5. Registra en DB
"""

from typing import Dict, List, Any, Optional
from dataclasses import dataclass


@dataclass
class BasketPnL:
    """P&L de una canasta de arbitraje completa."""
    position_id: int
    market_slug: str
    num_legs: int
    total_cost: float
    winning_outcome: str
    winning_shares: float
    revenue: float
    pnl: float
    pnl_pct: float
    leg_details: List[Dict[str, Any]]


class PnLCalculator:
    """
    Calcula P&L real por canasta de arbitraje.
    
    Agrupa trades por position_id y calcula el P&L considerando
    que todas las patas juntas forman un arbitraje completo.
    
    Uso:
        calculator = PnLCalculator(db)
        basket_pnl = calculator.calculate_basket_pnl(
            position_id=42,
            winning_outcome="YES",
            winning_shares=1.19,
        )
    """
    
    def __init__(self, db):
        self.db = db
    
    def calculate_basket_pnl(
        self,
        position_id: int,
        winning_outcome: str,
        winning_shares: float,
    ) -> BasketPnL:
        """
        Calcula P&L de una canasta de arbitraje completa.
        
        Args:
            position_id: ID de la canasta (vincula todas las patas)
            winning_outcome: Cuál outcome ganó ("YES" o "NO")
            winning_shares: Cuántos shares tenía la pata ganadora
            
        Returns:
            BasketPnL con detalles del P&L
        """
        # 1. Obtener todas las patas de la canasta
        trades = self.db.get_trades_by_position_id(position_id)
        
        if not trades:
            return BasketPnL(
                position_id=position_id,
                market_slug="unknown",
                num_legs=0,
                total_cost=0.0,
                winning_outcome=winning_outcome,
                winning_shares=0,
                revenue=0.0,
                pnl=0.0,
                pnl_pct=0.0,
                leg_details=[],
            )
        
        # 2. Calcular costo total de todas las patas
        total_cost = 0.0
        leg_details = []
        
        for trade in trades:
            cost = float(trade.get("total", 0) or 0)
            total_cost += cost
            leg_details.append({
                "trade_id": trade.get("id"),
                "symbol": trade.get("symbol"),
                "side": trade.get("side"),
                "price": float(trade.get("price", 0) or 0),
                "amount": float(trade.get("amount", 0) or 0),
                "total": cost,
                "token": self._extract_token(trade.get("symbol", "")),
            })
        
        # 3. Revenue = shares ganadores × $1.00
        revenue = winning_shares * 1.0
        
        # 4. P&L = revenue - costo_total
        pnl = revenue - total_cost
        
        # 5. P&L percentage
        pnl_pct = (pnl / total_cost * 100) if total_cost > 0 else 0.0
        
        # 6. Market slug
        market_slug = self._extract_market_slug(trades[0].get("symbol", "")) if trades else "unknown"
        
        return BasketPnL(
            position_id=position_id,
            market_slug=market_slug,
            num_legs=len(trades),
            total_cost=round(total_cost, 6),
            winning_outcome=winning_outcome,
            winning_shares=round(winning_shares, 6),
            revenue=round(revenue, 6),
            pnl=round(pnl, 6),
            pnl_pct=round(pnl_pct, 2),
            leg_details=leg_details,
        )
    
    def record_resolution(
        self,
        basket_pnl: BasketPnL,
        exit_reason: str = "market_resolved",
    ):
        """
        Registra la resolución en la base de datos.
        
        Args:
            basket_pnl: P&L calculado de la canasta
            exit_reason: Razón del cierre
        """
        # Actualizar posición en DB con P&L de canasta completa
        self.db.close_position(
            pos_id=basket_pnl.position_id,
            exit_price=1.0 if basket_pnl.pnl >= 0 else 0.0,
            exit_reason=exit_reason,
            pnl_override=basket_pnl.pnl,
            pnl_pct_override=basket_pnl.pnl_pct,
        )
        
        # Log del resultado
        if basket_pnl.pnl >= 0:
            self.db.log(
                "INFO",
                f"[PnLCalculator] Canasta {basket_pnl.position_id} resuelta: "
                f"+${basket_pnl.pnl:.4f} ({basket_pnl.pnl_pct:+.2f}%) "
                f"[{basket_pnl.winning_outcome} ganó, {basket_pnl.num_legs} patas]",
                "pnl_calculator",
            )
        else:
            self.db.log(
                "WARNING",
                f"[PnLCalculator] Canasta {basket_pnl.position_id} resuelta: "
                f"-${abs(basket_pnl.pnl):.4f} ({basket_pnl.pnl_pct:+.2f}%) "
                f"[{basket_pnl.winning_outcome} ganó, {basket_pnl.num_legs} patas]",
                "pnl_calculator",
            )
    
    def _extract_token(self, symbol: str) -> str:
        """Extrae el token (YES/NO) del symbol."""
        if not symbol:
            return "UNKNOWN"
        
        upper = symbol.upper()
        if upper.endswith("_YES"):
            return "YES"
        elif upper.endswith("_NO"):
            return "NO"
        
        return "YES"  # Default
    
    def _extract_market_slug(self, symbol: str) -> str:
        """Extrae el market_slug del symbol."""
        if not symbol:
            return "unknown"
        
        # Remover prefijos de plataforma
        prefixes = ["limitless_sport_", "polymarket_", "limitless_"]
        slug = symbol
        for prefix in prefixes:
            if slug.startswith(prefix):
                slug = slug[len(prefix):]
                break
        
        # Remover sufijo de outcome
        parts = slug.rsplit("_", 1)
        if len(parts) > 1:
            last = parts[-1].upper()
            if last in ("YES", "NO"):
                slug = parts[0]
        
        return slug if slug else "unknown"


# Singleton
_pnl_calculator: Optional[PnLCalculator] = None


def get_pnl_calculator(db=None) -> PnLCalculator:
    """Obtiene o crea la instancia global de PnLCalculator."""
    global _pnl_calculator
    if _pnl_calculator is None and db is not None:
        _pnl_calculator = PnLCalculator(db)
    return _pnl_calculator
