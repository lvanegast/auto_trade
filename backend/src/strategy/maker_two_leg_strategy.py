"""
Maker Two-Leg Strategy (Worker 6) — Arbitraje maker de 2 patas sobre mercados binarios up-or-down.

Patrón kacho.io / 1xN puro: comprar SIEMPRE las 2 patas (YES + NO) de un mercado binario.
Como maker (órdenes límite post-only, 0% fees), el costo de las 2 patas es:

    cost_yes = yes_bid                      # comprar YES al mejor bid (maker)
    cost_no  = no_bid = 1.0 - yes_ask       # comprar NO al mejor bid de NO (maker)

    total_maker_cost = yes_bid + no_bid = 1.0 - spread
    maker_edge       = 1.0 - total_maker_cost = spread

El spread ES el edge. Si ambas patas se llenan, se paga 1 - spread y se cobra 1.00
al settlement = beneficio garantizado. Si solo se llena una pata, se persigue el
hedge de la segunda (regla kacho: NUNCA dejar pata direccional suelta).

EJECUCIÓN REAL: emite 2 SignalEvent con order_type="GTC" (limit post-only, maker 0%).
OBSERVACIÓN: registra la oportunidad en edge_snapshots para paper-PnL sin tocar capital.
"""

import time
import os
from src.strategy.base import BaseStrategy
from src.events import PriceUpdateEvent, SignalEvent
from src.utils.bounded_dict import BoundedTimeDict


class MakerTwoLegStrategy(BaseStrategy):
    def __init__(
        self,
        symbol: str,
        min_edge_pct: float = 0.02,      # edge maker mínimo = spread mínimo (2%)
        position_size_usd: float = 1.0,  # monto USD por leg (fijo, min 1 / max 3)
        leg_size_min_usd: float = 1.0,   # mínimo por leg
        leg_size_max_usd: float = 3.0,   # máximo por leg
        db=None,
        worker_id: str = "worker_6",
        observation_only: bool = True,
        min_market_volume_usd: float = 25.0,  # volumen real transado mínimo para considerar el mercado "vivo"
    ):
        super().__init__(symbol)
        self.min_edge_pct = min_edge_pct
        # Presupuesto por leg fijo, limitado a [min, max]
        self.position_size_usd = max(
            leg_size_min_usd,
            min(position_size_usd, leg_size_max_usd),
        )
        self.leg_size_min_usd = leg_size_min_usd
        self.leg_size_max_usd = leg_size_max_usd
        self.db = db
        self.worker_id = worker_id
        self.observation_only = observation_only
        self.min_market_volume_usd = float(os.getenv("CRYPTO_MAKER_MIN_VOLUME_USD", "25.0")) or min_market_volume_usd

        # Estado de pares en curso: {slug: {"leg1": str, "leg2": str, "filled": [..]}}
        self._active_pairs: dict = {}
        self._position_id = None
        self._pending_signals: list = []
        self._last_signal_time: dict = {}
        self.cooldown_seconds = float(os.getenv("MAKER_COOLDOWN_SECONDS", "8.0"))

        # Contadores de diagnóstico por scan
        self._diag = {
            "markets_seen": 0, "no_book": 0, "edge_filtered": 0,
            "liquidity_filtered": 0, "cooldown": 0, "opportunities": 0,
        }

        # Telegram alert cooldowns — auto-expire after 1h
        self._last_telegram_alert = BoundedTimeDict(max_size=200, ttl_seconds=3600)

        # Stats
        self.total_pairs_sent = 0
        self.successful_pairs = 0

    def evaluate_signal(self, event: PriceUpdateEvent):
        return None

    def _reset_diag(self):
        self._diag = {
            "markets_seen": 0, "no_book": 0, "edge_filtered": 0,
            "liquidity_filtered": 0, "cooldown": 0, "opportunities": 0,
        }

    def on_price_update(self, event: PriceUpdateEvent) -> SignalEvent | None:
        super().on_price_update(event)

        # Check pending queue first (leg 2 of previous pair)
        if self._pending_signals:
            return self._pending_signals.pop(0)

        symbol = getattr(event, "symbol", "") or ""
        if not symbol or symbol.startswith("limitless_sniper_"):
            return None
        if symbol.startswith("limitless_crypto_"):
            slug = symbol[len("limitless_crypto_"):]
        elif symbol.startswith("oracle_"):
            slug = symbol[len("oracle_"):]
        else:
            slug = symbol

        self._diag["markets_seen"] += 1

        # Extraer book real (el feeder ya trae bid/ask del orderbook ejecutable)
        yes_bid = float(getattr(event, "bid", 0.0) or 0.0)
        yes_ask = float(getattr(event, "ask", 0.0) or 0.0)
        if yes_bid <= 0 or yes_ask <= 0 or yes_ask <= yes_bid:
            self._diag["no_book"] += 1
            return None

        # Book maker: comprar YES al bid; comprar NO al bid de NO (= 1 - yes_ask)
        cost_yes = round(yes_bid, 4)
        cost_no = round(1.0 - yes_ask, 4)
        if cost_no <= 0 or cost_yes <= 0:
            self._diag["no_book"] += 1
            return None

        total_maker_cost = round(cost_yes + cost_no, 4)
        maker_edge = round(1.0 - total_maker_cost, 4)
        if maker_edge < 0:
            return None

        # Filtro de mercado "vivo": el volumen real transado es la única prueba
        # de que las 2 patas se pueden llenar. Un book con millones de shares
        # pero volumen ~0 es postura lejana que jamás se cruza.
        market_volume = float(getattr(event, "market_volume", 0.0) or 0.0)
        if market_volume < self.min_market_volume_usd:
            self._diag["liquidity_filtered"] += 1
            return None

        # Liquidez: las 2 patas deben tener tamaño real en el book
        # bid_size/ask_size vienen en shares; convertir a USD para comparar con el presupuesto
        bid_size = float(getattr(event, "bid_size", 0.0) or 0.0)
        ask_size = float(getattr(event, "ask_size", 0.0) or 0.0)
        min_usd_liquidity = self.position_size_usd * 2.0

        now = time.time()
        last = self._last_signal_time.get(slug, 0.0)
        if now - last < self.cooldown_seconds:
            self._diag["cooldown"] += 1
            return None

        # Validar edge maker (spread) contra umbral + fricción (0% fees maker, gas 0.005)
        if maker_edge < self.min_edge_pct:
            self._diag["edge_filtered"] += 1
            return None

        # ADVERSE SELECTION PROTECTION: Si el spot líder (BTC/ETH en Binance)
        # se movió > 15 bps en los últimos 500ms, NO cotizar pasivamente para
        # evitar toxic fills (ser tomado por arbitrajistas más rápidos).
        asset = "BTC" if "btc" in slug.lower() else ("ETH" if "eth" in slug.lower() else "")
        if asset:
            from src.strategy.lead_lag_arbitrage import BinanceTracker
            is_jump, jump_bps = BinanceTracker.detect_jump(asset, window_seconds=0.5, threshold_bps=15.0)
            if is_jump:
                self._diag["adverse_selection"] = self._diag.get("adverse_selection", 0) + 1
                return None

        # Liquidez real en ambas patas (shares -> USD)
        yes_depth = round(bid_size * cost_yes, 2)   # USD de profundidad en el lado YES
        no_depth = round(ask_size * cost_no, 2)     # USD de profundidad en el lado NO
        if yes_depth < min_usd_liquidity or no_depth < min_usd_liquidity:
            self._diag["liquidity_filtered"] += 1
            return None

        # VALIDACIÓN DE FRICCIÓN MAKER (0% fees, gas mínimo)
        from src.engine.friction_guard import friction_guard
        is_profitable, net_edge, _reason, _details = friction_guard.validate_arbitrage_profitability(
            "limitless", "limitless", maker_edge, self.position_size_usd, execution_role="maker"
        )
        if not is_profitable:
            self._diag["edge_filtered"] += 1
            return None

        self._diag["opportunities"] += 1
        self._last_signal_time[slug] = now

        title = getattr(event, "chart_price", None) or slug
        gross_profit = maker_edge
        event_id = f"limitless_crypto_{slug}"

        # ---- OBSERVACIÓN (sin capital) ----
        if self.observation_only:
            try:
                if self.db and hasattr(self.db, "record_opportunity"):
                    self.db.record_opportunity({
                        "worker_id": self.worker_id,
                        "platform_a": "limitless",
                        "platform_b": "limitless",
                        "event_id": event_id,
                        "event_title": f"Crypto Maker 2-Leg: {slug[:40]}",
                        "gross_edge_pct": gross_profit * 100,
                        "net_edge_pct": net_edge * 100,
                        "platform_a_yes_ask": cost_yes,
                        "platform_b_no_ask": cost_no,
                        "platform_a_depth": yes_depth,
                        "platform_b_depth": no_depth,
                        "liquidity_verified": True,
                        "viable": True,
                        "entry_price": total_maker_cost,
                        "expected_profit": gross_profit * self.position_size_usd,
                        "category": "crypto",
                        "direction": "MAKER_2LEG_1XN",
                        "outcomes_count": 2,
                        "market_slug": slug,
                    })
                if self.db:
                    self.db.log(
                        "INFO",
                        f"[Maker 2-Leg OBS] {slug[:40]} | YES@bid={cost_yes:.4f} NO@bid={cost_no:.4f} "
                        f"Cost={total_maker_cost:.4f} | Edge(spread)={maker_edge:.2%} | Net={net_edge:.2%}",
                        self.worker_id,
                    )
                try:
                    from src.telegram_bot import telegram_bot
                    legs_detail = f"• YES @ {cost_yes:.4f} (prof: ${yes_depth:.2f})\n• NO @ {cost_no:.4f} (prof: ${no_depth:.2f})\n• Costo total: ${total_maker_cost:.4f}"
                    telegram_bot.send_opportunity(
                        event=f"Crypto Maker 2-Leg: {slug[:40]}",
                        edge=net_edge * 100,
                        platform_a="Limitless",
                        platform_b="Limitless",
                        event_id=event_id,
                        category="crypto",
                        worker_id=self.worker_id,
                        legs_detail=legs_detail,
                    )
                except Exception as tg_err:
                    if self.db:
                        self.db.log("WARNING", f"[Maker 2-Leg] error enviando alerta Telegram: {tg_err}", self.worker_id)
            except Exception as e:
                if self.db:
                    self.db.log("WARNING", f"[Maker 2-Leg] error registrando oportunidad: {e}", self.worker_id)
            return None

        # ---- EJECUCIÓN REAL: 2 patas GTC maker (post-only, 0% fees) ----
        self.total_pairs_sent += 1
        self._last_signal_time[slug] = now

        # Presupuesto FIJO por leg (min 1, max 3 USD), estilo Binance .fun:
        # cada pata (YES y NO) invierte exactamente leg_size_usd, sin balancear
        # el payout (a mayor edge, mayor ganancia por pata).
        leg_size_usd = self.position_size_usd
        usd_leg_yes = round(leg_size_usd, 4)
        usd_leg_no = round(leg_size_usd, 4)
        # Contratos que se compran con ese monto en cada pata (solo informativo)
        num_contracts = leg_size_usd / max(total_maker_cost, 0.01)

        reason_yes = (
            f"Maker 2-Leg [1/2]: BUY YES GTC @{cost_yes:.4f} | "
            f"Cost total par: {total_maker_cost:.4f} | Edge(spread): {maker_edge:.2%}"
        )
        reason_no = (
            f"Maker 2-Leg [2/2]: BUY NO GTC @{cost_no:.4f} | "
            f"Cost total par: {total_maker_cost:.4f} | Edge(spread): {maker_edge:.2%}"
        )

        # Leg 2 se encola y se ejecuta con FillGuard (si una pata falla → recovery/emergency sell)
        leg2_signal = SignalEvent(
            symbol=f"{event_id}_NO",
            side="BUY",
            price=cost_no,
            reason=reason_no,
            position_size_usd=usd_leg_no,
            position_id=None,
            order_type="GTC",
        )
        self._pending_signals.append(leg2_signal)

        # Track del par para seguimiento de fills
        self._active_pairs[slug] = {"filled": [], "cost": total_maker_cost}

        self.successful_pairs += 1
        if self.db:
            self.db.log(
                "INFO",
                f"💎 Par Maker Detectado | YES@bid {cost_yes:.4f} + NO@bid {cost_no:.4f} = {total_maker_cost:.4f} | "
                f"Edge(spread) {maker_edge:.2%} | Pairs: {self.successful_pairs}/{self.total_pairs_sent}",
                self.worker_id,
            )

        # Return Leg 1 (YES)
        return SignalEvent(
            symbol=f"{event_id}_YES",
            side="BUY",
            price=cost_yes,
            reason=reason_yes,
            position_size_usd=usd_leg_yes,
            position_id=None,
            order_type="GTC",
        )
