"""
Limitless Price Cache — Centralized executable price fetching from real orderbooks.

NEVER use prices[] from market listings — those are midpoints, not executable prices.
ALWAYS use this module to get real bid/ask from the Limitless orderbook.

Usage:
    from src.limitless_price_cache import get_limitless_executable_price

    price_info = get_limitless_executable_price("hanwha-life-esports-1785628800801")
    # Returns: {"yes_bid": 0.527, "yes_ask": 0.57, "bid_size": 100000000, "ask_size": 101000000}
"""

import time
import urllib.request
import json
import asyncio
from typing import Optional, Dict
from src.utils.bounded_dict import BoundedDict

# Cache: {slug: {"data": {...}, "ts": timestamp}} — bounded to prevent OOM
_cache: Dict[str, dict] = BoundedDict(max_size=200)
CACHE_TTL_SECONDS = 10  # Cache for 10 seconds


def _fetch_limitless_executable_price(slug: str, validate_maker_spread: bool = False) -> Optional[dict]:
    """
    Get real executable bid/ask from Limitless orderbook.

    Args:
        slug: Limitless market slug
        validate_maker_spread: If True, rejects books where spread > maxSpread (for maker strategies).
                               If False (default for takers), returns real executable book as long as
                               it is not uninitialized dust.

    Returns:
        {"yes_bid": float, "yes_ask": float, "bid_size": float, "ask_size": float, ...}
        or None if error.
    """
    now = time.time()

    # Fetch from orderbook API
    try:
        url = f"https://api.limitless.exchange/markets/{slug}/orderbook"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))

            bids = data.get("bids", [])
            asks = data.get("asks", [])

            if not bids or not asks:
                return None

            best_bid = float(bids[0].get("price", 0))
            best_ask = float(asks[0].get("price", 0))
            bid_size = float(bids[0].get("size", 0))
            ask_size = float(asks[0].get("size", 0))

            if best_bid <= 0 or best_ask <= 0 or best_ask <= best_bid:
                return None

            # Reject uninitialized placeholder dust (seed spread >= 98% with 0.001/0.999)
            if best_bid <= 0.01 and best_ask >= 0.99:
                return None

            spread = best_ask - best_bid
            max_spread = float(data.get("maxSpread", 0.035))
            adjusted_mid = data.get("adjustedMidpoint")

            # For maker 2-leg strategies, reject wide spreads where maker orders will never fill.
            # For takers, spreads outside maxSpread are completely valid executable books.
            if validate_maker_spread and spread > max_spread:
                return None

            if adjusted_mid is not None:
                adjusted_mid = float(adjusted_mid)
                if adjusted_mid < 0.001 or adjusted_mid > 0.999:
                    return None

            result = {
                "yes_bid": best_bid,
                "yes_ask": best_ask,
                "bid_size": bid_size,
                "ask_size": ask_size,
                "no_ask": round(1.0 - best_bid, 4),
                "no_bid": round(1.0 - best_ask, 4),
                "spread": round(spread, 4),
                "max_spread": round(max_spread, 4),
            }

            # Update cache
            _cache[slug] = {"data": result, "ts": now}

            return result
    except Exception:
        return None


def get_limitless_executable_price(slug: str, validate_maker_spread: bool = False) -> Optional[dict]:
    """Return only a fresh cached executable book; never block the event loop."""
    cached = _cache.get(slug)
    if cached and time.time() - cached["ts"] < CACHE_TTL_SECONDS:
        data = cached["data"]
        if validate_maker_spread and data.get("spread", 0) > data.get("max_spread", 0.035):
            return None
        return data
    return None


async def async_get_limitless_executable_price(slug: str, validate_maker_spread: bool = False) -> Optional[dict]:
    """Async entry point; keeps blocking legacy HTTP off the event loop."""
    cached = get_limitless_executable_price(slug, validate_maker_spread=validate_maker_spread)
    if cached is not None:
        return cached
    return await asyncio.to_thread(_fetch_limitless_executable_price, slug, validate_maker_spread)



def clear_cache():
    """Clear the price cache."""
    _cache.clear()


def get_cache_stats() -> dict:
    """Get cache statistics."""
    return {
        "entries": len(_cache),
        "ttl_seconds": CACHE_TTL_SECONDS,
    }
