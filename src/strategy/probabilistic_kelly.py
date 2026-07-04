import numpy as np
from src.strategy.base import BaseStrategy
from src.events import PriceUpdateEvent, SignalEvent


class ProbabilisticKellyStrategy(BaseStrategy):
    def __init__(
        self,
        symbol: str,
        prior_alpha: float = 12.0,
        prior_beta: float = 12.0,
        kelly_scale: float = 0.25,
        min_edge: float = 0.02,
    ):
        super().__init__(symbol)

        # Parámetros Bayesianos (Beta Prior)
        self.alpha_prior = prior_alpha
        self.beta_prior = prior_beta

        # Criterio de Kelly
        self.kelly_scale = kelly_scale
        self.min_edge = min_edge

        # Historial de cambios de precio para actualización
        self.price_history = []
        self.last_position = None  # 'BUY', 'SELL', None
        self.last_signal_price = 0.0

        # Variables expuestas para el API
        self.teorical_probability = 0.50
        self.market_price = 0.50
        self.edge = 0.0
        self.kelly_recommendation = 0.0

    def evaluate_signal(self, event: PriceUpdateEvent) -> SignalEvent:
        """Evaluación principal de la estrategia sobre barra cerrada."""
        # En esta estrategia, la lógica corre principalmente sobre on_price_update en tiempo real
        # ya que la gestión de Kelly y la actualización Bayesiana ocurren tick a tick.
        return None

    def on_price_update(self, event: PriceUpdateEvent) -> SignalEvent:
        """Sobrescribe el comportamiento base para procesar cada actualización de precio tick-a-tick."""
        # 1. Agregar el precio al DataFrame base
        super().on_price_update(event)

        current_price = event.price
        self.market_price = current_price

        # Determinar si es un mercado de predicción (precio < 1.5) o criptomonedas
        is_binary = current_price < 1.5

        # Registrar cambio de precio para la actualización Bayesiana
        if len(self.price_history) > 0:
            current_price - self.price_history[-1]
            self.price_history.append(current_price)
        else:
            self.price_history.append(current_price)

        if len(self.price_history) > 40:
            self.price_history.pop(0)

        # 2. Calcular Probabilidad Teórica (p)
        if is_binary:
            p = self._estimate_binary_probability(event)
            self.teorical_probability = p

            # 3. Calcular Edge y Fracción de Kelly
            # Para contratos binarios, odds b = (1 - q) / q
            q = max(0.01, min(0.99, current_price))
            b = (1.0 - q) / q

            # Edge = p * b - (1 - p)
            self.edge = p * b - (1.0 - p)

            # Criterio de Kelly: f* = scale * (p * b - (1 - p)) / b
            if self.edge > self.min_edge:
                self.kelly_recommendation = self.kelly_scale * (self.edge / b)
            elif self.edge < -self.min_edge:
                # Edge negativo fuerte sugiere comprar la opción contraria (NO)
                # que equivale a vender/ponerse corto
                self.kelly_recommendation = self.kelly_scale * (self.edge / b)
            else:
                self.kelly_recommendation = 0.0
        else:
            # Caso Criptomonedas (Retornos continuos)
            p, mu, sigma2 = self._estimate_continuous_parameters()
            self.teorical_probability = p

            # En retornos continuos, Kelly f* = scale * mu / sigma2
            if sigma2 > 0:
                raw_kelly = mu / sigma2
                # Limitar recomendación razonable de apalancamiento
                self.kelly_recommendation = self.kelly_scale * max(
                    -2.0, min(2.0, raw_kelly)
                )
                self.edge = mu
            else:
                self.kelly_recommendation = 0.0
                self.edge = 0.0

        # 4. Generar Señales basadas en Criterio de Kelly
        signal = None
        # Si la recomendación de Kelly es significativamente positiva y no estamos comprados
        if self.kelly_recommendation > 0.05 and self.last_position != "BUY":
            self.last_position = "BUY"
            self.last_signal_price = current_price
            signal = SignalEvent(
                symbol=self.symbol,
                side="BUY",
                price=current_price,
                reason=f"Edge Bayesiano positivo ({self.edge:+.4f}) con Kelly sugerido {self.kelly_recommendation:.2%}",
                amount=abs(self.kelly_recommendation),
            )
        # Si la recomendación de Kelly es significativamente negativa y estamos comprados (o queremos vender)
        elif self.kelly_recommendation < -0.05 and self.last_position != "SELL":
            self.last_position = "SELL"
            self.last_signal_price = current_price
            signal = SignalEvent(
                symbol=self.symbol,
                side="SELL",
                price=current_price,
                reason=f"Edge Bayesiano negativo ({self.edge:+.4f}) con Kelly sugerido {self.kelly_recommendation:.2%}",
                amount=abs(self.kelly_recommendation),
            )

        return signal

    def _estimate_binary_probability(self, event: PriceUpdateEvent) -> float:
        """Estima la probabilidad bayesiana de que ocurra el evento YES."""
        # Contar éxitos (subidas) y fracasos (bajadas) en el historial reciente
        prices = np.array(self.price_history)
        if len(prices) < 2:
            return 0.50

        diffs = np.diff(prices)
        successes = np.sum(diffs > 0)
        failures = np.sum(diffs < 0)

        # Calcular posterior de Beta
        alpha_post = self.alpha_prior + successes
        beta_post = self.beta_prior + failures
        p_bayes = alpha_post / (alpha_post + beta_post)

        # Calcular Order Book Imbalance (OBI)
        # OBI = (price - bid) / (ask - bid) para ver la presión de compra
        if event.ask is not None and event.bid is not None and event.ask > event.bid:
            obi = (event.price - event.bid) / (event.ask - event.bid)
            # Acotar OBI
            obi = max(0.0, min(1.0, obi))
        else:
            obi = 0.50

        # P probabilidad ajustada combinando Bayes y la presión a muy corto plazo del OBI
        p_adjusted = p_bayes * 0.85 + obi * 0.15
        return float(max(0.01, min(0.99, p_adjusted)))

    def _estimate_continuous_parameters(self):
        """Estima la deriva (mu) y la varianza (sigma2) de retornos continuos de criptomonedas."""
        prices = np.array(self.price_history)
        if len(prices) < 5:
            return 0.50, 0.0, 0.0

        # Retornos logarítmicos
        log_returns = np.diff(np.log(prices))

        mu = np.mean(log_returns)
        sigma2 = np.var(log_returns)

        # Probabilidad de retorno positivo en la siguiente barra
        positives = np.sum(log_returns > 0)
        p = positives / len(log_returns)

        return float(p), float(mu), float(sigma2)
