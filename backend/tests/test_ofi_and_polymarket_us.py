"""
Unit tests for Order Flow Imbalance (OFI) tracker and Polymarket US Gateway parsing.
"""

import time
from src.engine.order_flow_imbalance import OrderFlowImbalanceTracker, ofi_tracker


def test_ofi_calculation():
    """Test instantaneous OFI calculations across consecutive book updates."""
    tracker = OrderFlowImbalanceTracker()
    tracker.clear()
    sym = "BTCUSDT"

    # Initial book: Bid 60000 @ 10, Ask 60001 @ 10
    t0 = time.monotonic()
    ofi0 = tracker.record_book_ticker(sym, 60000.0, 10.0, 60001.0, 10.0, timestamp=t0)
    assert ofi0 == 0.0

    # Tick 1: Aggressive buyers push bid price up to 60000.5 @ 15
    # delta_bid = 15.0, delta_ask = 0 (ask unchanged at 60001 @ 10)
    ofi1 = tracker.record_book_ticker(sym, 60000.5, 15.0, 60001.0, 10.0, timestamp=t0 + 0.1)
    assert ofi1 == 15.0

    # Tick 2: Buyers eat ask, new ask is 60001.5 @ 8
    # delta_bid = 0, delta_ask = -prev_ask_qty = -10.0
    # ofi = 0 - (-10) = +10.0
    ofi2 = tracker.record_book_ticker(sym, 60000.5, 15.0, 60001.5, 8.0, timestamp=t0 + 0.2)
    assert ofi2 == 10.0

    # Normalized OFI should be strongly bullish
    norm_ofi, regime = tracker.get_normalized_ofi(sym, window_seconds=2.0)
    assert norm_ofi > 0.30
    assert regime == "BULLISH_PRESSURE"


def test_ofi_bearish_pressure():
    """Test bearish OFI regime when sellers dominate."""
    tracker = OrderFlowImbalanceTracker()
    tracker.clear()
    sym = "ETHUSDT"

    t0 = time.monotonic()
    tracker.record_book_ticker(sym, 3000.0, 50.0, 3001.0, 50.0, timestamp=t0)

    # Sellers drop ask price to 3000.5 @ 80
    # delta_ask = 80, delta_bid = 0 -> ofi = -80
    tracker.record_book_ticker(sym, 3000.0, 50.0, 3000.5, 80.0, timestamp=t0 + 0.1)

    # Sellers eat bids, bid drops to 2999.0 @ 40
    # delta_bid = -50, delta_ask = 0 -> ofi = -50
    tracker.record_book_ticker(sym, 2999.0, 40.0, 3000.5, 80.0, timestamp=t0 + 0.2)

    norm_ofi, regime = tracker.get_normalized_ofi(sym, window_seconds=2.0)
    assert norm_ofi < -0.30
    assert regime == "BEARISH_PRESSURE"


def test_polymarket_us_drawable_and_moneyline():
    """Test parsing logic for Polymarket US Gateway events."""
    from src.utils.event_id import make_match_event_id

    # Test 3-way soccer event
    event_title = "Chelsea FC vs. Hull City AFC"
    m_title = "Chelsea FC (Reg. Time)"
    clean_name = m_title.replace("(Reg. Time)", "").strip()
    ev_id = make_match_event_id(event_title, clean_name)
    assert "chelsea" in ev_id
    assert "hull" in ev_id

    # Test Tie/Draw
    draw_id = make_match_event_id(event_title, "Draw")
    assert "draw" in draw_id


if __name__ == "__main__":
    test_ofi_calculation()
    test_ofi_bearish_pressure()
    test_polymarket_us_drawable_and_moneyline()
    print("SUCCESS: All OFI and Polymarket US tests passed!")
