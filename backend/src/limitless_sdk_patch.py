"""
SDK patch — makes limitless-sdk orderbook parsing tolerant of null values.

The Limitless API returns `lastTradePrice: null` for markets that have not
traded yet. The SDK model `OrderBook.last_trade_price` is declared as a required
`float`, so pydantic raises a `ValidationError` and MarketFetcher.get_orderbook()
blows up for those markets. This silently killed sports group arb (every group
with an untraded sub-market was discarded as "no liquidity").

This module relaxes the field to `Optional[float] = None` so orderbooks for
untraded markets parse correctly. It must be imported BEFORE any code path that
calls `MarketFetcher.get_orderbook()`.
"""

from typing import Optional


def apply_sdk_patch():
    try:
        import limitless_sdk.types.markets as tm
        from pydantic.fields import FieldInfo

        current = tm.OrderBook.model_fields.get("last_trade_price")
        if current is None:
            return
        if current.annotation is not None and getattr(current.annotation, "_name", None) == "Optional":
            return

        tm.OrderBook.model_fields["last_trade_price"] = FieldInfo(
            annotation=Optional[float],
            alias="lastTradePrice",
            default=None,
        )
        tm.OrderBook.__annotations__["last_trade_price"] = Optional[float]
        tm.OrderBook.model_rebuild(force=True)
    except Exception:
        pass


apply_sdk_patch()
