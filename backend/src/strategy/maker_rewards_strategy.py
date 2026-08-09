"""
Maker Liquidity Rewards Strategy (Worker 6) — Módulo de Arbitraje Maker & Captura de Recompensas de Liquidez.

En lugar de pagar comisiones Taker, esta estrategia publica órdenes LIMIT tipo Maker al mejor Bid disponible (Midpoint - Spread/2).
Gana $0.00 comisiones + Captura Recompensas Diarias por Aportar Liquidez + Retorno del Spread ($1.00 - Total Cost).
"""

import time
from src.strategy.base import BaseStrategy
from src.events import PriceUpdateEvent, SignalEvent


class MakerLiquidityRewardsStrategy(BaseStrategy):
    def __init__(
        self,
        symbol: str,
        position_size_usd: float = 50.0,
        min_rebate_edge_pct: float = 0.015, # 1.5% de margen Maker mínimo
        cooldown_seconds: float = 5.0,
        db=None,
        worker_id: str = "worker_6",
        observation_only: bool = True,
        min_market_volume_usd: float = 25.0,
    ):
        super().__init__(symbol)
        self.position_size_usd = position_size_usd
        self.min_rebate_edge_pct = min_rebate_edge_pct
        self.cooldown_seconds = cooldown_seconds
        self.db = db
        self.worker_id = worker_id
        self.observation_only = observation_only
        self.min_market_volume_usd = min_market_volume_usd

        self.last_position = None
        self.entry_price = 0.0
        self.last_exit_time = 0.0
        self.teorical_probability = 0.50
        self.edge = 0.0
        self.kelly_recommendation = 0.0
        self._position_id = None

    def evaluate_signal(self, df):
        """Método abstracto de BaseStrategy."""
        return None

    def on_price_update(self, event: PriceUpdateEvent) -> SignalEvent:
        super().on_price_update(event)

        real_bid = getattr(event, "bid", 0.0)
        real_ask = getattr(event, "ask", 0.0)
        if real_bid <= 0 or real_ask <= 0:
            return None

        # Filtro de mercado "vivo": volumen real transado mínimo.
        # La profundidad del book (millones de shares) es postura lejana que jamás
        # llena la pata complementaria; sin volumen real el spread-gap es fantasma.
        market_volume = float(getattr(event, "market_volume", 0.0) or 0.0)
        if market_volume < self.min_market_volume_usd:
            return None

        self.teorical_probability = (real_bid + real_ask) / 2.0

        now = time.time()
        if (now - self.last_exit_time) < self.cooldown_seconds:
            return None

        # Estrategia Maker: Publicar orden LIMIT al precio Bid actual (Maker Price)
        maker_buy_price = real_bid
        maker_no_price = 1.0 - real_ask
        total_maker_cost = maker_buy_price + maker_no_price

        # Calcular ventaja neta Maker ($0 comisiones + rebate de liquidez)
        maker_edge = 1.0 - total_maker_cost
        self.edge = maker_edge

        if maker_edge >= self.min_rebate_edge_pct:
            # Validar con el escudo de fricción Maker (0% fee + $0 gas en Maker Limit Orders)
            from src.engine.friction_guard import friction_guard
            is_profitable, net_edge, _reason, _details = friction_guard.validate_arbitrage_profitability(
                "limitless", "limitless", maker_edge, self.position_size_usd
            )

            if is_profitable:
                expected_profit = (1.0 - total_maker_cost) * self.position_size_usd
                reason = (
                    f"Maker Liquidity Rewards: LIMIT BUY @ {maker_buy_price:.4f} | "
                    f"Maker Cost: {total_maker_cost:.4f} | Edge: {maker_edge:.2%} | "
                    f"Rebate Est: +$0.05/day | Profit Neto: ${expected_profit:.2f}"
                )

                self.last_position = "BUY_LIMIT"
                self.entry_price = maker_buy_price
                self.last_exit_time = now

                if self.db:
                    self.db.log("INFO", f"[Maker-Reward] 💎 {reason}", self.worker_id)

                # ---- OBSERVACIÓN (sin capital) ----
                if self.observation_only:
                    try:
                        slug = getattr(event, "market_slug", None) or self.symbol
                        if self.db and hasattr(self.db, "record_opportunity"):
                            self.db.record_opportunity({
                                "worker_id": self.worker_id,
                                "platform_a": "limitless",
                                "platform_b": "limitless",
                                "event_id": f"limitless_crypto_{slug}",
                                "event_title": f"Maker Rewards (spread-gap): {slug[:40]}",
                                "gross_edge_pct": maker_edge * 100,
                                "net_edge_pct": net_edge * 100,
                                "platform_a_yes_ask": maker_buy_price,
                                "platform_b_no_ask": maker_no_price,
                                "platform_a_depth": getattr(event, "bid_size", 0.0),
                                "platform_b_depth": getattr(event, "ask_size", 0.0),
                                "liquidity_verified": True,
                                "viable": True,
                                "entry_price": total_maker_cost,
                                "expected_profit": expected_profit,
                                "category": "crypto",
                                "direction": "MAKER_REWARDS_SPREAD_GAP",
                                "outcomes_count": 2,
                                "market_slug": slug,
                            })
                    except Exception:
                        pass
                    return None

                # ---- EJECUCIÓN REAL: orden límite maker post-only (0% fees) ----
                base_symbol = getattr(event, "symbol", None) or self.symbol
                if not base_symbol.startswith("limitless_crypto_"):
                    base_symbol = f"limitless_crypto_{base_symbol}"
                return SignalEvent(
                    symbol=f"{base_symbol}_YES",
                    side="BUY",
                    price=maker_buy_price,
                    reason=reason,
                    position_size_usd=self.position_size_usd,
                    position_id=None,
                    order_type="GTC",
                )

        return None
