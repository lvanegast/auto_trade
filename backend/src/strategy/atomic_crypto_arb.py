import time
import random
from src.strategy.base import BaseStrategy
from src.events import PriceUpdateEvent, SignalEvent


class AtomicCryptoArbStrategy(BaseStrategy):
    """
    Atomic Multicall / Bundle Arbitrage Strategy.
    Simulates atomic transaction bundling on Base L2 for prediction markets.
    Applies limit order bids (Maker) for both YES and NO contracts to lock in
    a combined cost strictly under $1.00 USD.
    """

    def __init__(
        self,
        symbol: str,
        min_profit_target: float = 0.015,  # 1.5% profit target
        position_size_usd: float = 10.0,
        db=None,
        worker_id: str = "worker_6",
    ):
        super().__init__(symbol)
        self.min_profit_target = min_profit_target
        self.position_size_usd = position_size_usd
        self.db = db
        self.worker_id = worker_id

        self.last_position = None
        self._position_id = None
        self._last_signal_time = 0.0
        self.cooldown_seconds = 4.0

        self._pending_signals = []

        # High-fidelity stats
        self.total_bundles_sent = 0
        self.successful_bundles = 0
        self.reverted_bundles = 0
        self.gas_burned_usd = 0.0

        self.teorical_probability = 0.50
        self.edge = 0.0
        self.kelly_recommendation = 0.0

    def evaluate_signal(self, event):
        return None

    def on_price_update(self, event: PriceUpdateEvent) -> SignalEvent | None:
        super().on_price_update(event)

        # Check pending queue first
        if self._pending_signals:
            return self._pending_signals.pop(0)

        # Filter: match base_asset unless configured for ANY-INTRADAY (which scans all same-day elements)
        if self.symbol != "ANY-INTRADAY":
            base_asset = self.symbol.split("-")[0].lower()
            if base_asset not in event.symbol.lower():
                return None

        now = time.time()
        
        # 10-minute safety cooldown check on previous revert / loss
        if hasattr(self, "_revert_suspension_until") and now < self._revert_suspension_until:
            return None
            
        if now - self._last_signal_time < self.cooldown_seconds:
            return None

        # Filter: Only enter markets that expire on the SAME DAY (less than 24 hours / 86400 seconds)
        exp_ts = getattr(event, "expiration_timestamp", None)
        if exp_ts and (exp_ts - now > 86400):
            return None

        # Check orderbook availability
        bid_yes = event.bid
        ask_yes = event.ask
        if bid_yes <= 0 or ask_yes <= 0:
            return None

        # Taker execution:
        # Buy YES at the current ask_yes
        my_ask_yes = ask_yes
        # Buy NO at the current ask_no. On prediction platforms, ask_no is equivalent to (1.0 - bid_yes)
        # because the bid of YES defines the ask of NO (buying NO is taking the YES bid).
        my_ask_no = round(1.0 - bid_yes, 4)

        # The total cost of buying both as Taker is my_ask_yes + my_ask_no
        total_cost = round(my_ask_yes + my_ask_no, 4)
        gross_profit = round(1.0 - total_cost, 4)

        self.teorical_probability = (bid_yes + ask_yes) / 2.0
        self.edge = gross_profit

        # Does the gross margin meet our minimum profit target?
        if gross_profit >= self.min_profit_target:
            self.total_bundles_sent += 1
            
            # --- 1. SIMULATE LATENCY & SLIPPAGE / REVERT ---
            # Represents execution slippage on-chain
            latency_revert = random.random() < 0.15  # 15% chance of slippage/revert
            
            if latency_revert:
                self.reverted_bundles += 1
                revert_gas = 0.001
                self.gas_burned_usd += revert_gas
                # Suspend strategy for 10 minutes to protect capital
                self._revert_suspension_until = now + 600.0
                reason = f"[Atomic-Revert] ⛽ Maker bundle falló por frontrun. Gas quemado: ${revert_gas:.4f} | Penalización: Suspendido por 10 min | Suma: {total_cost:.4f}"
                if self.db:
                    self.db.log("WARNING", reason, self.worker_id)
                return None
            
            # --- 2. SUCCESSFUL DUAL LIMIT ORDER FILL ---
            self.successful_bundles += 1
            self._last_signal_time = now

            # Number of contracts to buy per leg to balance the payout:
            # S = position_size_usd / total_cost
            num_contracts = self.position_size_usd / max(total_cost, 0.01)
            usd_leg_yes = round(num_contracts * my_ask_yes, 4)
            usd_leg_no = round(num_contracts * my_ask_no, 4)

            reason_yes = (
                f"Atomic-Taker Arb [Leg 1/2]: YES @{my_ask_yes:.4f} | "
                f"Costo Total: {total_cost:.4f} | Edge: {gross_profit:.2%} | Net Profit: ${gross_profit * num_contracts:.4f}"
            )
            reason_no = (
                f"Atomic-Taker Arb [Leg 2/2]: NO @{my_ask_no:.4f} | "
                f"Costo Total: {total_cost:.4f} | Edge: {gross_profit:.2%} | Net Profit: ${gross_profit * num_contracts:.4f}"
            )

            # Queue Leg 2 (NO)
            leg2_signal = SignalEvent(
                symbol=f"{event.symbol}_NO",
                side="BUY",
                price=my_ask_no,
                reason=reason_no,
                position_size_usd=usd_leg_no,
                position_id=None
            )
            self._pending_signals.append(leg2_signal)

            if self.db:
                self.db.log("INFO", f"💎 Arbitraje Taker Detectado | YES Ask @{my_ask_yes:.4f} + NO Ask @{my_ask_no:.4f} = {total_cost:.4f} | Bundles: {self.successful_bundles}/{self.total_bundles_sent}", self.worker_id)

            # Return Leg 1 (YES)
            return SignalEvent(
                symbol=f"{event.symbol}_YES",
                side="BUY",
                price=my_ask_yes,
                reason=reason_yes,
                position_size_usd=usd_leg_yes,
                position_id=None
            )

        return None
