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


def _fetch_limitless_executable_price(slug: str) -> Optional[dict]:
    """
    Get real executable bid/ask from Limitless orderbook.

    Returns:
        {"yes_bid": float, "yes_ask": float, "bid_size": float, "ask_size": float}
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

            result = {
                "yes_bid": best_bid,
                "yes_ask": best_ask,
                "bid_size": bid_size,
                "ask_size": ask_size,
                "no_ask": round(1.0 - best_bid, 4),
                "no_bid": round(1.0 - best_ask, 4),
            }

            # Update cache
            _cache[slug] = {"data": result, "ts": now}

            return result
    except Exception as e:
        return None


def get_limitless_executable_price(slug: str) -> Optional[dict]:
    """Return only a fresh cached executable book; never block the event loop."""
    cached = _cache.get(slug)
    if cached and time.time() - cached["ts"] < CACHE_TTL_SECONDS:
        return cached["data"]
    return None


async def async_get_limitless_executable_price(slug: str) -> Optional[dict]:
    """Async entry point; keeps blocking legacy HTTP off the event loop."""
    cached = get_limitless_executable_price(slug)
    if cached is not None:
        return cached
    return await asyncio.to_thread(_fetch_limitless_executable_price, slug)


def clear_cache():
    """Clear the price cache."""
    _cache.clear()


def get_cache_stats() -> dict:
    """Get cache statistics."""
    return {
        "entries": len(_cache),
        "ttl_seconds": CACHE_TTL_SECONDS,
    }
