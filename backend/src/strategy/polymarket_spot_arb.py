import math
import datetime
from src.strategy.base import BaseStrategy
from src.strategy.lead_lag_arbitrage import BinanceTracker
from src.events import SignalEvent


def phi(x: float) -> float:
    """Distribución normal acumulativa para el modelo Black-Scholes."""
    return (1.0 + math.erf(x / math.sqrt(2.0))) / 2.0


class PolymarketSpotArbStrategy(BaseStrategy):
    """
    Estrategia Cuantitativa de Arbitraje entre Opciones Binarias de Polymarket y Spot en Vivo de Binance.
    Aplica el modelo de Black-Scholes para opciones digital/cash-or-nothing:
    P_teórica = N(d2)
    """

    def __init__(
        self,
        symbol: str,
        strike_price: float = 64000.0,
        expiration_time: datetime.datetime = None,
        volatility: float = 0.35,
        min_edge_pct: float = 0.04,
        position_size_pct: float = 0.10,
        db=None,
        worker_id: str = "worker_3",
    ):
        super().__init__(symbol)
        self.db = db
        self.worker_id = worker_id
        self.strike_price = strike_price
        self.volatility = volatility
        self.min_edge_pct = min_edge_pct
        self.position_size_pct = position_size_pct

        if expiration_time is None:
            # Por defecto expira al final del día
            self.expiration_time = datetime.datetime.now(
                datetime.timezone.utc
            ) + datetime.timedelta(hours=6)
        else:
            self.expiration_time = expiration_time

        self.last_position = None
        self._position_id = None
        self.event_id = "btc_price_spot_arbitrage"

        self.teorical_probability = 0.50
        self.edge = 0.0
        self.kelly_recommendation = 0.0

    def calculate_theoretical_probability(self, spot_price: float) -> float:
        now = datetime.datetime.now(datetime.timezone.utc)
        exp_utc = self.expiration_time
        if exp_utc.tzinfo is None:
            exp_utc = exp_utc.replace(tzinfo=datetime.timezone.utc)

        time_to_expiry = (exp_utc - now).total_seconds() / (365.0 * 86400.0)

        if time_to_expiry <= 0:
            return 1.0 if spot_price >= self.strike_price else 0.0

        r = 0.04  # Tasa libre de riesgo (4%)
        sigma = self.volatility

        d2 = (
            math.log(spot_price / self.strike_price)
            + (r - 0.5 * sigma**2) * time_to_expiry
        ) / (sigma * math.sqrt(time_to_expiry))

        prob = phi(d2)
        return max(0.01, min(0.99, prob))

    def evaluate_signal(self, event):
        return None

    def on_price_update(self, event) -> SignalEvent | None:
        super().on_price_update(event)

        spot_price = BinanceTracker.latest_btc_price
        if spot_price <= 0:
            return None

        self.teorical_probability = self.calculate_theoretical_probability(spot_price)

        ask_yes = event.ask
        bid_yes = event.bid

        edge_buy_yes = self.teorical_probability - ask_yes
        edge_buy_no = bid_yes - self.teorical_probability

        signal = None

        if self.last_position is None:
            if edge_buy_yes >= self.min_edge_pct:
                self.edge = edge_buy_yes
                kelly = (self.edge / max(ask_yes, 0.01)) * self.position_size_pct
                self.kelly_recommendation = max(0.0, min(0.20, kelly))

                self.last_position = "BUY"
                self._position_id = int(datetime.datetime.now().timestamp())

                signal = SignalEvent(
                    symbol=self.symbol,
                    side="BUY",
                    price=ask_yes,
                    reason=f"Polymarket Spot-Arb: YES subvalorado @{ask_yes:.4f} vs Spot BTC ${spot_price:,.0f} (Teor: {self.teorical_probability:.2%})",
                    amount=self.kelly_recommendation,
                    position_id=self._position_id,
                )

            elif edge_buy_no >= self.min_edge_pct:
                self.edge = edge_buy_no
                cost_no = 1.0 - bid_yes
                kelly = (self.edge / max(cost_no, 0.01)) * self.position_size_pct
                self.kelly_recommendation = max(0.0, min(0.20, kelly))

                self.last_position = "SELL"
                self._position_id = int(datetime.datetime.now().timestamp())

                signal = SignalEvent(
                    symbol=self.symbol,
                    side="SELL",
                    price=bid_yes,
                    reason=f"Polymarket Spot-Arb: NO subvalorado @{cost_no:.4f} vs Spot BTC ${spot_price:,.0f} (Teor: {1 - self.teorical_probability:.2%})",
                    amount=self.kelly_recommendation,
                    position_id=self._position_id,
                )
        else:
            if self.last_position == "BUY" and edge_buy_yes < 0.01:
                signal = SignalEvent(
                    symbol=self.symbol,
                    side="SELL",
                    price=bid_yes,
                    reason="Cierre de Arbitraje YES: Precios convergieron con Spot.",
                    position_id=self._position_id,
                )
                self.last_position = None
                self._position_id = None
                self.edge = 0.0
                self.kelly_recommendation = 0.0

            elif self.last_position == "SELL" and edge_buy_no < 0.01:
                signal = SignalEvent(
                    symbol=self.symbol,
                    side="BUY",
                    price=ask_yes,
                    reason="Cierre de Arbitraje NO: Precios convergieron con Spot.",
                    position_id=self._position_id,
                )
                self.last_position = None
                self._position_id = None
                self.edge = 0.0
                self.kelly_recommendation = 0.0

        return signal
