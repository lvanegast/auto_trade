"""
OrderBookWalker — simula fills caminando el order book real.

En vez de asumir fill al mid-price, consume liquidez nivel por nivel
según el tamaño de la posición, aplicando delay artificial = latencia medida.

Uso:
    walker = OrderBookWalker()
    fill = walker.simulate_fill(
        orderbook={"bids": [...], "asks": [...]},
        side="BUY",
        size_usd=5.0,
        latency_ms=150.0,  # latencia medida real
    )
    print(f"Fill price: {fill.avg_price}, Slippage: {fill.slippage_pct}%")
"""

import time
from typing import List, Dict, Optional, Any
from dataclasses import dataclass


@dataclass
class OrderBookLevel:
    """Un nivel del order book."""
    price: float
    size: float  # En contratos o shares
    
    @property
    def size_usd(self) -> float:
        return self.price * self.size


@dataclass
class FillResult:
    """Resultado de simular un fill caminando el book."""
    avg_price: float  # Precio promedio ponderado del fill
    total_filled: float  # Cantidad total filled (contratos)
    total_cost: float  # Costo total en USD
    levels_consumed: int  # Niveles del book consumidos
    slippage_pct: float  # Slippage vs mejor precio (%)
    slippage_usd: float  # Slippage en USD
    best_price: float  # Mejor precio disponible (nivel 0)
    worst_price: float  # Peor precio del fill (último nivel)
    fill_time_ms: float  # Tiempo estimado del fill
    partial_fill: bool  # Si no se llenó completamente
    unfilled_usd: float  # USD no llenado (si partial)
    levels: List[Dict]  # Detalle de cada nivel consumido


class OrderBookWalker:
    """
    Simula fills caminando el order book real.
    
    Características:
    - Consume liquidez nivel por nivel según tamaño de posición
    - Aplica delay artificial = latencia medida (el book puede cambiar)
    - Calcula slippage real vs mejor precio
    - Detecta fills parciales (book sin suficiente liquidez)
    """
    
    def simulate_fill(
        self,
        orderbook: Dict,
        side: str,
        size_usd: float,
        latency_ms: float = 0.0,
    ) -> FillResult:
        """
        Simula un fill caminando el order book.
        
        Args:
            orderbook: Dict con 'bids' y 'asks' (listas de {price, size})
            side: 'BUY' o 'SELL'
            size_usd: Tamaño de la posición en USD
            latency_ms: Latencia artificial a aplicar (del LatencyTracker)
            
        Returns:
            FillResult con detalles del fill simulado
        """
        # Seleccionar el lado del book según la dirección
        if side == "BUY":
            levels_raw = orderbook.get("asks", [])
        else:
            levels_raw = orderbook.get("bids", [])
        
        if not levels_raw:
            return FillResult(
                avg_price=0.0,
                total_filled=0.0,
                total_cost=0.0,
                levels_consumed=0,
                slippage_pct=0.0,
                slippage_usd=0.0,
                best_price=0.0,
                worst_price=0.0,
                fill_time_ms=latency_ms,
                partial_fill=True,
                unfilled_usd=size_usd,
                levels=[],
            )
        
        # Parsear niveles del order book
        levels = []
        for level in levels_raw:
            if isinstance(level, dict):
                price = float(level.get("price", 0))
                size = float(level.get("size", 0))
            elif isinstance(level, (list, tuple)) and len(level) >= 2:
                price, size = float(level[0]), float(level[1])
            else:
                continue
            
            if price > 0 and size > 0:
                levels.append(OrderBookLevel(price=price, size=size))
        
        if not levels:
            return FillResult(
                avg_price=0.0,
                total_filled=0.0,
                total_cost=0.0,
                levels_consumed=0,
                slippage_pct=0.0,
                slippage_usd=0.0,
                best_price=0.0,
                worst_price=0.0,
                fill_time_ms=latency_ms,
                partial_fill=True,
                unfilled_usd=size_usd,
                levels=[],
            )
        
        # Caminar el book consumiendo liquidez
        best_price = levels[0].price
        remaining_usd = size_usd
        total_filled = 0.0
        total_cost = 0.0
        levels_consumed = 0
        levels_detail = []
        
        for level in levels:
            if remaining_usd <= 0:
                break
            
            # Cuántos contratos podemos comprar a este precio
            level_capacity_usd = level.size_usd
            fill_usd = min(remaining_usd, level_capacity_usd)
            fill_contracts = fill_usd / level.price
            
            total_filled += fill_contracts
            total_cost += fill_usd
            remaining_usd -= fill_usd
            levels_consumed += 1
            
            levels_detail.append({
                "price": level.price,
                "size_contracts": fill_contracts,
                "size_usd": fill_usd,
                "cumulative_usd": total_cost,
            })
        
        # Calcular métricas
        avg_price = total_cost / total_filled if total_filled > 0 else 0.0
        worst_price = levels_detail[-1]["price"] if levels_detail else best_price
        
        # Slippage
        if side == "BUY":
            slippage_pct = ((avg_price - best_price) / best_price * 100) if best_price > 0 else 0.0
        else:
            slippage_pct = ((best_price - avg_price) / best_price * 100) if best_price > 0 else 0.0
        
        slippage_usd = abs(avg_price - best_price) * total_filled
        
        # Tiempo estimado: latencia + tiempo proporcional por nivel
        # Asumimos ~1ms por nivel adicional después del primero
        fill_time_ms = latency_ms + (levels_consumed - 1) * 1.0
        
        return FillResult(
            avg_price=round(avg_price, 6),
            total_filled=round(total_filled, 6),
            total_cost=round(total_cost, 6),
            levels_consumed=levels_consumed,
            slippage_pct=round(slippage_pct, 4),
            slippage_usd=round(slippage_usd, 6),
            best_price=best_price,
            worst_price=worst_price,
            fill_time_ms=round(fill_time_ms, 2),
            partial_fill=remaining_usd > 0.001,
            unfilled_usd=round(max(0, remaining_usd), 6),
            levels=levels_detail,
        )
    
    def estimate_slippage(
        self,
        orderbook: Dict,
        side: str,
        size_usd: float,
    ) -> float:
        """
        Estima el slippage sin simular el fill completo.
        Útil para validación rápida antes de decidir ejecutar.
        
        Returns:
            Slippage estimado en porcentaje (0.0 = sin slippage)
        """
        fill = self.simulate_fill(orderbook, side, size_usd)
        return fill.slippage_pct


# Singleton global
orderbook_walker = OrderBookWalker()
