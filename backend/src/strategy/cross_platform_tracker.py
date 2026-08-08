"""
CrossPlatformTracker — almacena libros de órdenes en tiempo real de ambas plataformas
para que las estrategias de arbitraje puedan detectar oportunidades con precios ejecutables.

Cambios vs. versión anterior:
  - Almacena bid/ask/depth por nivel, NO solo midpoint
  - NO se derive como 1 - YES; se almacena el ask real de NO por separado
  - Stale check en milisegundos (500ms), no segundos
  - Cada snapshot lleva: timestamp_origen, recepcion_local, book_age_ms, sequence
"""

import time
import os
from typing import Optional
from src.utils.bounded_dict import BoundedDict


class CrossPlatformTracker:
    """
    Almacena el último libro de órdenes conocido de cada contrato en ambas plataformas.

    Estructura interna:
        _books = {
            "event_id": {
                "kalshi": {
                    "yes_bid": 0.64, "yes_ask": 0.66,
                    "no_bid": 0.34, "no_ask": 0.36,
                    "bid_depth": 500.0, "ask_depth": 300.0,
                    "ts_origin": ..., "ts_local": ..., "sequence": ...,
                },
                "limitless": { ... },
            }
        }
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._books = BoundedDict(max_size=500)
        return cls._instance

    def update_book(
        self,
        event_id: str,
        platform: str,
        yes_bid: float,
        yes_ask: float,
        no_bid: float = None,
        no_ask: float = None,
        bid_depth: float = 0.0,
        ask_depth: float = 0.0,
        ts_origin: float = None,
        sequence: int = None,
    ):
        """
        Actualiza el libro de órdenes completo de un contrato en una plataforma.

        Args:
            event_id: ID lógico del evento
            platform: 'kalshi', 'limitless', 'polymarket'
            yes_bid: Mejor bid para YES
            yes_ask: Mejor ask para YES (precio al que puedo COMPRAR YES)
            no_bid: Mejor bid para NO (opcional, se deriva si no se provee)
            no_ask: Mejor ask para NO (opcional, se deriva si no se provee)
            bid_depth: Profundidad total en la capa de bids (USD o contratos)
            ask_depth: Profundidad total en la capa de asks
            ts_origin: Timestamp del origen (exchange clock)
            sequence: Número de secuencia del libro
        """
        now = time.time()

        if no_bid is None:
            no_bid = round(1.0 - yes_ask, 4)
        if no_ask is None:
            no_ask = round(1.0 - yes_bid, 4)

        if event_id not in self._books:
            self._books[event_id] = {}

        self._books[event_id][platform] = {
            "yes_bid": yes_bid,
            "yes_ask": yes_ask,
            "no_bid": no_bid,
            "no_ask": no_ask,
            "bid_depth": bid_depth,
            "ask_depth": ask_depth,
            "ts_origin": ts_origin or now,
            "ts_local": now,
            "sequence": sequence,
            "book_age_ms": (now - ts_origin) * 1000 if ts_origin else 0,
        }

    def update_price(
        self,
        event_id: str,
        platform: str,
        price: float,
        bid: float = None,
        ask: float = None,
    ):
        """Store an executable book; midpoint-only updates are rejected."""
        if bid is None or ask is None or bid >= ask:
            raise ValueError(
                "update_price requires a real orderbook bid/ask; midpoint-only updates are rejected"
            )
        yes_bid = bid
        yes_ask = ask
        self.update_book(
            event_id=event_id,
            platform=platform,
            yes_bid=yes_bid,
            yes_ask=yes_ask,
        )

    def get_book(self, event_id: str, platform: str) -> Optional[dict]:
        return self._books.get(event_id, {}).get(platform)

    def get_both_books(self, event_id: str) -> dict:
        return dict(self._books.get(event_id, {}))

    def get_all_event_ids(self) -> list[str]:
        return list(self._books.keys())

    def is_book_stale(self, event_id: str, platform: str, max_age_ms: float = 500.0) -> bool:
        book = self.get_book(event_id, platform)
        if book is None:
            return True
        return book["book_age_ms"] > max_age_ms

    def calculate_arbitrage(
        self,
        event_id: str,
        min_edge_pct: float = 0.02,
        max_staleness_ms: Optional[float] = None,
    ) -> Optional[dict]:
        """
        Calcula arbitraje usando precios EJECUTABLES (ask para comprar).

        Compara TODAS las plataformas presentes (kalshi, limitless, polymarket,
        sx_bet, ...) por pares y devuelve la mejor oportunidad de arbitraje cruzado:

          - Puedo comprar YES al ask de la plataforma A
          - Puedo comprar NO al ask de la plataforma B
          - Si yes_ask_A + no_ask_B < 1.0, hay arbitraje garantizado

        El edge = 1.0 - (yes_ask_A + no_ask_B)
        """
        books = self._books.get(event_id, {})
        platforms = [p for p in books if p != "oracle"]
        if len(platforms) < 2:
            return None

        now = time.time()
        if max_staleness_ms is None:
            max_staleness_ms = float(os.getenv("CROSS_ARB_MAX_STALENESS_MS", "5000"))

        best = None
        # Considera todos los pares ordenados (A, B), A != B
        for a in platforms:
            for b in platforms:
                if a == b:
                    continue
                book_a = books[a]
                book_b = books[b]
                a_age_ms = (now - book_a["ts_local"]) * 1000
                b_age_ms = (now - book_b["ts_local"]) * 1000
                if a_age_ms > max_staleness_ms or b_age_ms > max_staleness_ms:
                    continue

                a_yes_ask = book_a["yes_ask"]
                b_no_ask = book_b["no_ask"]
                cost = a_yes_ask + b_no_ask
                edge = 1.0 - cost
                if edge < min_edge_pct:
                    continue

                candidate = {
                    "direction": f"BUY_YES_{a.upper()}_BUY_NO_{b.upper()}",
                    "buy_platform": a,
                    "buy_side": "YES",
                    "buy_ask": a_yes_ask,
                    "hedge_platform": b,
                    "hedge_side": "NO",
                    "hedge_ask": b_no_ask,
                    "total_cost": cost,
                    "guaranteed_profit": edge,
                    "edge_pct": edge,
                    "buy_depth": book_a["ask_depth"],
                    "hedge_depth": book_b["ask_depth"],
                    "buy_book_age_ms": a_age_ms,
                    "hedge_book_age_ms": b_age_ms,
                }
                if best is None or edge > best["edge_pct"]:
                    best = candidate

        if best:
            best["event_id"] = event_id
            best["timestamp"] = now

        return best

    def scan_all_pairs(self, min_edge_pct: float = 0.02) -> list[dict]:
        opportunities = []
        for event_id in self._books:
            opp = self.calculate_arbitrage(event_id, min_edge_pct)
            if opp:
                opportunities.append(opp)
        return opportunities

    def clear(self):
        self._books.clear()


cross_platform_tracker = CrossPlatformTracker()
