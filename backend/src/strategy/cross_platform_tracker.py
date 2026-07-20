"""
CrossPlatformTracker: Singleton que almacena precios en tiempo real de ambos platforms
para que las estrategias de arbitraje puedan comparar precios cross-platform.

Patrón similar a BinanceTracker pero para mercados de predicción.
Soporta: kalshi, limitless, polymarket (legacy).
"""


class CrossPlatformTracker:
    """
    Almacena el último precio conocido de cada contrato en ambos platforms.
    Cada estrategia escribe su propio precio y lee el del otro platform.

    Estructura interna:
        _prices = {
            "event_id": {
                "kalshi": {"price": 0.65, "bid": 0.64, "ask": 0.66, "ts": ...},
                "limitless": {"price": 0.60, "bid": 0.59, "ask": 0.61, "ts": ...},
            }
        }
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._prices = {}
        return cls._instance

    def update_price(
        self,
        event_id: str,
        platform: str,
        price: float,
        bid: float = None,
        ask: float = None,
    ):
        """
        Actualiza el precio conocido de un contrato en un platform.

        Args:
            event_id: ID lógico del evento (ej: 'fed_rate_july_2026')
            platform: 'kalshi' o 'polymarket'
            price: Precio actual (midpoint o último trade)
            bid: Mejor bid (opcional)
            ask: Mejor ask (opcional)
        """
        import time

        if event_id not in self._prices:
            self._prices[event_id] = {}

        self._prices[event_id][platform] = {
            "price": price,
            "bid": bid if bid is not None else price,
            "ask": ask if ask is not None else price,
            "ts": time.time(),
        }

    def get_price(self, event_id: str, platform: str) -> dict | None:
        """Retorna el último precio conocido de un contrato en un platform."""
        return self._prices.get(event_id, {}).get(platform)

    def get_both_prices(self, event_id: str) -> dict:
        """
        Retorna precios de ambos platforms para un evento.

        Returns:
            {
                "kalshi": {"price": ..., "bid": ..., "ask": ..., "ts": ...} | None,
                "limitless": {"price": ..., "bid": ..., "ask": ..., "ts": ...} | None,
            }
        """
        return {
            "kalshi": self._prices.get(event_id, {}).get("kalshi"),
            "limitless": self._prices.get(event_id, {}).get("limitless"),
        }

    def get_all_event_ids(self) -> list[str]:
        """Retorna todos los event_ids con datos disponibles."""
        return list(self._prices.keys())

    def calculate_arbitrage(
        self,
        event_id: str,
        min_edge_pct: float = 0.02,
        max_staleness_sec: float = 30.0,
    ) -> dict | None:
        """
        Calcula si existe oportunidad de arbitraje para un evento.

        Lógica:
            Para un contrato binario YES/NO, el arbitraje existe cuando:
                buy_yes_price平台A + buy_no_price平台B < 1.0

            buy_no en un平台 = 1.0 - buy_yes
            spread = 1.0 - (yes_A + (1 - yes_B))
                   = yes_B - yes_A (si compro YES barato en A y NO barato en B)

        Returns:
            dict con detalles de la oportunidad o None si no hay arbitraje.
        """
        import time

        both = self.get_both_prices(event_id)
        kalshi = both["kalshi"]
        limitless = both["limitless"]

        if kalshi is None or limitless is None:
            return None

        # Verificar que los datos no estén obsoletos
        now = time.time()
        if (now - kalshi["ts"]) > max_staleness_sec:
            return None
        if (now - limitless["ts"]) > max_staleness_sec:
            return None

        k_yes = kalshi["price"]
        l_yes = limitless["price"]

        # Escenario 1: Comprar YES en Kalshi, NO en Limitless
        # Costo = k_yes + (1 - l_yes)
        cost_1 = k_yes + (1.0 - l_yes)
        edge_1 = 1.0 - cost_1  # Ganancia garantizada por contrato

        # Escenario 2: Comprar YES en Limitless, NO en Kalshi
        # Costo = l_yes + (1 - k_yes)
        cost_2 = l_yes + (1.0 - k_yes)
        edge_2 = 1.0 - cost_2

        best = None
        if edge_1 > edge_2 and edge_1 >= min_edge_pct:
            best = {
                "direction": "BUY_YES_KALSHI_SELL_NO_LIMITLESS",
                "buy_platform": "kalshi",
                "buy_side": "YES",
                "buy_price": k_yes,
                "hedge_platform": "limitless",
                "hedge_side": "NO",
                "hedge_price": 1.0 - l_yes,
                "total_cost": cost_1,
                "guaranteed_profit": edge_1,
                "edge_pct": edge_1,
            }
        elif edge_2 >= min_edge_pct:
            best = {
                "direction": "BUY_YES_LIMITLESS_SELL_NO_KALSHI",
                "buy_platform": "limitless",
                "buy_side": "YES",
                "buy_price": l_yes,
                "hedge_platform": "kalshi",
                "hedge_side": "NO",
                "hedge_price": 1.0 - k_yes,
                "total_cost": cost_2,
                "guaranteed_profit": edge_2,
                "edge_pct": edge_2,
            }

        if best:
            best["event_id"] = event_id
            best["kalshi_yes"] = k_yes
            best["limitless_yes"] = l_yes
            best["timestamp"] = now

        return best

    def scan_all_pairs(self, min_edge_pct: float = 0.02) -> list[dict]:
        """
        Escanea todos los eventos disponibles y retorna oportunidades de arbitraje.
        """
        opportunities = []
        for event_id in self._prices:
            opp = self.calculate_arbitrage(event_id, min_edge_pct)
            if opp:
                opportunities.append(opp)
        return opportunities

    def clear(self):
        """Limpia todos los precios almacenados."""
        self._prices.clear()


# Singleton global
cross_platform_tracker = CrossPlatformTracker()
