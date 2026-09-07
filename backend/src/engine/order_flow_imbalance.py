"""
Order Flow Imbalance (OFI) Engine for High-Frequency Microstructure Analysis.

Based on Cont, Kukanov & Stoikov (2014) "The Price Impact of Order Book Events":
Tracks net volume changes at the top of the order book across consecutive bookTicker events:

    ΔQ_bid:
        +Q_bid(t)               if P_bid(t) > P_bid(t-1)  (price improved, aggressive buyer interest)
        Q_bid(t) - Q_bid(t-1)   if P_bid(t) == P_bid(t-1) (depth change at same best bid)
        -Q_bid(t-1)             if P_bid(t) < P_bid(t-1)  (bid depleted or cancelled)

    ΔQ_ask:
        -Q_ask(t-1)             if P_ask(t) > P_ask(t-1)  (ask depleted or lifted)
        Q_ask(t) - Q_ask(t-1)   if P_ask(t) == P_ask(t-1) (depth change at same best ask)
        +Q_ask(t)               if P_ask(t) < P_ask(t-1)  (ask improved, aggressive seller interest)

    OFI_t = ΔQ_bid - ΔQ_ask

Positive OFI indicates net buyer pressure (future price move UP).
Negative OFI indicates net seller pressure (future price move DOWN).
"""

import time
from collections import deque
from typing import Dict, Optional, Tuple


class OrderFlowImbalanceTracker:
    """
    Singleton tracker for real-time Order Flow Imbalance across market data streams.
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._prev_levels: Dict[str, Tuple[float, float, float, float]] = {}
            # Rolling window of OFI ticks: {symbol: deque([(timestamp, ofi_val, total_depth)])}
            cls._instance._history: Dict[str, deque] = {}
        return cls._instance

    def record_book_ticker(
        self,
        symbol: str,
        bid_price: float,
        bid_qty: float,
        ask_price: float,
        ask_qty: float,
        timestamp: Optional[float] = None,
    ) -> float:
        """
        Processes a top-of-book update and returns instantaneous OFI.
        """
        if bid_price <= 0 or ask_price <= 0:
            return 0.0

        now = timestamp or time.monotonic()
        key = symbol.upper().replace("/", "").replace("-", "")

        prev = self._prev_levels.get(key)
        self._prev_levels[key] = (bid_price, bid_qty, ask_price, ask_qty)

        if key not in self._history:
            self._history[key] = deque(maxlen=300)

        if prev is None:
            self._history[key].append((now, 0.0, (bid_qty + ask_qty) / 2.0))
            return 0.0

        prev_bid_p, prev_bid_q, prev_ask_p, prev_ask_q = prev

        # 1. Delta Bid Volume
        if bid_price > prev_bid_p:
            delta_bid = bid_qty
        elif bid_price == prev_bid_p:
            delta_bid = bid_qty - prev_bid_q
        else:
            delta_bid = -prev_bid_q

        # 2. Delta Ask Volume
        if ask_price < prev_ask_p:
            delta_ask = ask_qty
        elif ask_price == prev_ask_p:
            delta_ask = ask_qty - prev_ask_q
        else:
            delta_ask = -prev_ask_q

        # 3. Instantaneous OFI
        ofi = delta_bid - delta_ask
        total_depth = (bid_qty + ask_qty) / 2.0

        if key not in self._history:
            self._history[key] = deque(maxlen=300)

        self._history[key].append((now, ofi, total_depth))
        return ofi

    def get_normalized_ofi(self, symbol: str, window_seconds: float = 3.0) -> Tuple[float, str]:
        """
        Returns normalized rolling OFI in range [-1.0, +1.0] and direction regime:
            - 'BULLISH_PRESSURE' (ofi_norm > +0.30)
            - 'BEARISH_PRESSURE' (ofi_norm < -0.30)
            - 'NEUTRAL'

        Normalization is sum(OFI) / sum(Depth) over the window.
        """
        key = symbol.upper().replace("/", "").replace("-", "")
        history = self._history.get(key)
        if not history or len(history) < 2:
            return 0.0, "NEUTRAL"

        now = time.monotonic()
        cutoff = now - window_seconds

        sum_ofi = 0.0
        sum_depth = 0.0

        for t_stamp, ofi_val, depth in history:
            if t_stamp >= cutoff:
                sum_ofi += ofi_val
                sum_depth += depth

        if sum_depth <= 1e-9:
            return 0.0, "NEUTRAL"

        # Normalized ratio
        norm_val = sum_ofi / sum_depth
        norm_val = max(-1.0, min(1.0, norm_val))
        norm_val = round(norm_val, 4)

        if norm_val > 0.30:
            regime = "BULLISH_PRESSURE"
        elif norm_val < -0.30:
            regime = "BEARISH_PRESSURE"
        else:
            regime = "NEUTRAL"

        return norm_val, regime

    def clear(self):
        self._prev_levels.clear()
        self._history.clear()


ofi_tracker = OrderFlowImbalanceTracker()
