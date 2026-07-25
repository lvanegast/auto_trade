"""
Market Making Strategy for Limitless Binary Markets.

Places orders on BOTH sides of the orderbook:
  - BUY YES at (fair_value - half_spread)  → bid side
  - SELL YES at (fair_value + half_spread) → ask side

Profit comes from:
  1. Spread capture (buy low, sell high on same asset)
  2. Maker rebates from Limitless (daily USDC rewards for providing liquidity)

Inventory management:
  - If holding too much YES → lower the ask to attract sellers
  - If holding too much NO → lower the bid to attract buyers
  - Max inventory cap prevents runaway exposure
"""

import asyncio
import os
import time
from src.strategy.base import BaseStrategy
from src.events import PriceUpdateEvent, SignalEvent


class MarketMakingStrategy(BaseStrategy):
    def __init__(
        self,
        symbol: str,
        position_size_usd: float = 25.0,
        half_spread_pct: float = 0.02,
        min_spread_pct: float = 0.01,
        max_inventory: int = 5,
        inventory_skew_pct: float = 0.005,
        cooldown_seconds: float = 10.0,
        min_edge_pct: float = 0.005,
        db=None,
        worker_id: str = "worker_4",
    ):
        super().__init__(symbol)
        self.position_size_usd = position_size_usd
        self.half_spread_pct = half_spread_pct
        self.min_spread_pct = min_spread_pct
        self.max_inventory = max_inventory
        self.inventory_skew_pct = inventory_skew_pct
        self.cooldown_seconds = cooldown_seconds
        self.min_edge_pct = min_edge_pct
        self.db = db
        self.worker_id = worker_id

        self.last_signal_time = 0.0
        self.yes_inventory = 0
        self.no_inventory = 0
        self.total_trades = 0
        self.total_spread_captured = 0.0
        self._position_id = None

        self.teorical_probability = 0.50
        self.edge = 0.0
        self.kelly_recommendation = 0.0

    def evaluate_signal(self, df):
        return None

    def on_price_update(self, event: PriceUpdateEvent) -> SignalEvent:
        super().on_price_update(event)

        real_bid = getattr(event, "bid", 0.0)
        real_ask = getattr(event, "ask", 0.0)
        if real_bid <= 0 or real_ask <= 0:
            return None

        now = time.time()
        if (now - self.last_signal_time) < self.cooldown_seconds:
            return None

        spread = real_ask - real_bid
        if spread < 0:
            return None

        fair_value = (real_bid + real_ask) / 2.0
        self.teorical_probability = fair_value

        market_spread_pct = (spread / fair_value) * 100 if fair_value > 0 else 0

        my_half_spread = self.half_spread_pct

        if self.yes_inventory >= self.max_inventory:
            my_half_spread -= self.inventory_skew_pct * (self.yes_inventory - self.no_inventory)
        elif self.no_inventory >= self.max_inventory:
            my_half_spread -= self.inventory_skew_pct * (self.no_inventory - self.yes_inventory)

        my_half_spread = max(self.min_spread_pct, my_half_spread)

        my_bid = round(fair_value - my_half_spread, 4)
        my_ask = round(fair_value + my_half_spread, 4)

        my_bid = max(0.01, min(0.99, my_bid))
        my_ask = max(0.01, min(0.99, my_ask))

        if my_bid >= my_ask:
            return None

        my_spread = my_ask - my_bid
        if my_spread < self.min_spread_pct:
            return None

        can_buy = self.yes_inventory < self.max_inventory
        can_sell = self.no_inventory < self.max_inventory

        if not can_buy and not can_sell:
            return None

        # Selección inteligente de la mejor oportunidad de cotización en el libro
        best_action = None
        best_edge = 0.0

        # Si tenemos inventario cargado hacia YES, priorizar venta de YES (SELL) para equilibrar y asegurar ganancia
        if self.yes_inventory > self.no_inventory and can_sell:
            best_action = "SELL"
            best_edge = my_ask - real_bid if real_bid > 0 else self.min_edge_pct
        elif self.no_inventory > self.yes_inventory and can_buy:
            best_action = "BUY"
            best_edge = real_ask - my_bid if real_ask > 0 else self.min_edge_pct
        else:
            # Si el inventario está equilibrado, cotizar en la punta que ofrezca mayor margen neta
            buy_edge = real_ask - my_bid if real_ask > 0 else 0.0
            sell_edge = my_ask - real_bid if real_bid > 0 else 0.0

            if buy_edge >= sell_edge and can_buy:
                best_action = "BUY"
                best_edge = max(buy_edge, self.min_edge_pct)
            elif can_sell:
                best_action = "SELL"
                best_edge = max(sell_edge, self.min_edge_pct)

        if best_action is None:
            return None

        self.edge = best_edge
        self.kelly_recommendation = max(0.01, best_edge / 0.10)

        if best_action == "BUY":
            self.yes_inventory += 1
            if self.no_inventory > 0:
                self.no_inventory -= 1
            price = my_bid
            reason = (
                f"[Market Making 💎] BID Creado YES @ ${my_bid:.4f} | "
                f"Precio Justo: ${fair_value:.4f} | Spread Capturado: ${spread:.4f} ({market_spread_pct:.1f}%) | "
                f"Inventario: YES={self.yes_inventory} NO={self.no_inventory} | Edge Neto: +{best_edge:.2%}"
            )
        else:
            self.no_inventory += 1
            if self.yes_inventory > 0:
                self.yes_inventory -= 1
            price = my_ask
            reason = (
                f"[Market Making 💎] ASK Creado YES @ ${my_ask:.4f} | "
                f"Precio Justo: ${fair_value:.4f} | Spread Capturado: ${spread:.4f} ({market_spread_pct:.1f}%) | "
                f"Inventario: YES={self.yes_inventory} NO={self.no_inventory} | Edge Neto: +{best_edge:.2%}"
            )

        self.last_signal_time = now
        self.total_trades += 1
        self.total_spread_captured += best_edge

        if self.db:
            self.db.log("INFO", reason, self.worker_id)

        return SignalEvent(
            symbol=self.symbol,
            side=best_action,
            price=price,
            reason=reason,
            amount=self.position_size_usd / max(price, 0.01),
            position_id=self._position_id,
        )
