from datetime import datetime


class TradingEvent:
    def __init__(self, event_type: str):
        self.event_type = event_type
        self.timestamp = datetime.now()


class PriceUpdateEvent(TradingEvent):
    def __init__(self, symbol: str, price: float, ask: float = None, bid: float = None):
        super().__init__("PRICE_UPDATE")
        self.symbol = symbol
        self.price = price
        self.ask = ask if ask is not None else price
        self.bid = bid if bid is not None else price

    def __str__(self):
        return f"[PriceUpdate] {self.symbol}: {self.price:.4f} (Bid: {self.bid}, Ask: {self.ask})"


class SignalEvent(TradingEvent):
    def __init__(self, symbol: str, side: str, price: float, reason: str = "", amount: float = None):
        super().__init__("SIGNAL")
        self.symbol = symbol
        self.side = side.upper()  # 'BUY' o 'SELL'
        self.price = price
        self.reason = reason
        self.amount = amount

    def __str__(self):
        amount_str = f" x {self.amount}" if self.amount is not None else ""
        return f"[Signal] {self.symbol} -> {self.side}{amount_str} @ {self.price:.4f} (Reason: {self.reason})"


class OrderEvent(TradingEvent):
    def __init__(
        self,
        symbol: str,
        side: str,
        price: float,
        amount: float,
        status: str = "PENDING",
        order_id: str = None,
    ):
        super().__init__("ORDER")
        self.symbol = symbol
        self.side = side.upper()
        self.price = price
        self.amount = amount
        self.status = status  # 'PENDING', 'COMPLETED', 'FAILED'
        self.order_id = order_id

    def __str__(self):
        return f"[Order] {self.side} {self.amount} {self.symbol} @ {self.price:.4f} [{self.status}]"
