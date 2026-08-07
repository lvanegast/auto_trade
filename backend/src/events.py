from datetime import datetime, timezone
from uuid import uuid4


class TradingEvent:
    def __init__(self, event_type: str, timestamp: datetime | None = None, event_id: str = None):
        self.event_id = event_id or uuid4().hex[:16]
        self.event_type = event_type
        # El timestamp pertenece al dato de mercado, no al navegador que lo
        # renderiza. Usar UTC evita mezclar horas locales/naive entre el
        # historial, el motor y los clientes WebSocket.
        if isinstance(timestamp, str):
            try:
                dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                self.timestamp = dt
            except Exception:
                self.timestamp = datetime.now(timezone.utc)
        elif isinstance(timestamp, (int, float)):
            self.timestamp = datetime.fromtimestamp(timestamp, tz=timezone.utc)
        else:
            self.timestamp = timestamp or datetime.now(timezone.utc)
        
        if hasattr(self.timestamp, "tzinfo") and self.timestamp.tzinfo is None:
            self.timestamp = self.timestamp.replace(tzinfo=timezone.utc)


class PriceUpdateEvent(TradingEvent):
    def __init__(
        self,
        symbol: str,
        price: float,
        ask: float = None,
        bid: float = None,
        timestamp: datetime | None = None,
        chart_price: float | None = None,
    ):
        super().__init__("PRICE_UPDATE", timestamp=timestamp)
        self.symbol = symbol
        self.price = price
        self.ask = ask if ask is not None else price
        self.bid = bid if bid is not None else price
        # El motor puede operar con mid-price, mientras la gráfica conserva el
        # último precio negociado para coincidir con las velas históricas.
        self.chart_price = chart_price

    def __str__(self):
        return f"[PriceUpdate] {self.symbol}: {self.price:.4f} (Bid: {self.bid}, Ask: {self.ask})"


class SignalEvent(TradingEvent):
    def __init__(
        self,
        symbol: str,
        side: str,
        price: float,
        reason: str = "",
        amount: float = None,
        position_id: int = None,
        position_size_usd: float = None,
        order_type: str = None,
    ):
        super().__init__("SIGNAL")
        self.symbol = symbol
        self.side = side.upper()  # 'BUY' o 'SELL'
        self.price = price
        self.reason = reason
        self.amount = amount
        self.position_id = position_id
        self.position_size_usd = position_size_usd
        self.order_type = order_type  # 'GTC' for limit orders (maker=0% fee), None for market orders

    def __str__(self):
        amount_str = f" x {self.amount}" if self.amount is not None else ""
        usd_str = f" (${self.position_size_usd:.2f})" if self.position_size_usd is not None else ""
        order_str = f" [{self.order_type}]" if self.order_type else ""
        return f"[Signal] {self.symbol} -> {self.side}{amount_str}{usd_str} @ {self.price:.4f}{order_str} (Reason: {self.reason})"


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
