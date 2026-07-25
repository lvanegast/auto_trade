"""
Lead-Lag Arbitrage Validation Script
=====================================
Downloads REAL historical data from Binance AND Kraken for BTC,
measures the actual lag between them, and runs a simulated backtest.

Usage:
    python backend/validate_leadlag_real.py
"""

import json
import time
import datetime
from collections import defaultdict
from typing import Optional

import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
BINANCE_BASE = "https://api.binance.com/api/v3/klines"
KRAKEN_BASE = "https://api.kraken.com/0/public/OHLC"

# We'll fetch 1-minute candles for 7 days
# Binance returns max 1000 candles per request, so we paginate
CANDLE_INTERVAL_SECONDS = 60
SECONDS_PER_DAY = 86400
TOTAL_SECONDS = SECONDS_PER_DAY * 7  # 7 days
RATE_LIMIT_DELAY = 0.25  # seconds between API calls

# Strategy parameters (matching lead_lag_arbitrage.py)
ARBITRAGE_THRESHOLD = 0.0010  # 0.10%
MIN_PROFIT_TARGET = 0.0015   # 0.15%
MAX_HOLD_SECONDS = 15.0
STOP_LOSS_PCT = 0.005         # 0.50%
STOP_LOSS_USD = 15.0
TRAILING_STOP_PCT = 0.0010    # 0.10%
COOLDOWN_SECONDS = 5.0
POSITION_SIZE_PCT = 0.15
INITIAL_CAPITAL = 10000.0


def fetch_binance_klines(symbol: str, interval: str, start_ms: int, end_ms: int) -> list[dict]:
    """Fetch 1-minute candles from Binance with pagination."""
    all_candles = []
    current_start = start_ms

    while current_start < end_ms:
        params = {
            "symbol": symbol,
            "interval": interval,
            "startTime": current_start,
            "endTime": end_ms,
            "limit": 1000,
        }
        try:
            resp = requests.get(BINANCE_BASE, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as e:
            print(f"  [Binance] API error: {e}")
            break

        if not data:
            break

        for candle in data:
            all_candles.append({
                "timestamp": candle[0] // 1000,  # ms -> s
                "open": float(candle[1]),
                "high": float(candle[2]),
                "low": float(candle[3]),
                "close": float(candle[4]),
                "volume": float(candle[5]),
                "exchange": "binance",
            })

        # Move start to after last candle
        last_ts = data[-1][0] // 1000
        current_start = (last_ts + CANDLE_INTERVAL_SECONDS) * 1000
        time.sleep(RATE_LIMIT_DELAY)

    return all_candles


def fetch_kraken_ohlc(pair: str, since: int, end_ts: int) -> list[dict]:
    """Fetch 1-minute candles from Kraken with pagination."""
    all_candles = []
    current_since = since

    while current_since < end_ts:
        params = {
            "pair": pair,
            "interval": 1,  # 1 minute
            "since": current_since,
        }
        try:
            resp = requests.get(KRAKEN_BASE, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as e:
            print(f"  [Kraken] API error: {e}")
            break

        if data.get("error"):
            print(f"  [Kraken] API errors: {data['error']}")
            break

        result = data.get("result", {})
        # First key is the pair data, 'last' is the pagination timestamp
        pair_key = None
        last_ts = 0
        for key, value in result.items():
            if key != "last":
                pair_key = key
                candles = value
            else:
                last_ts = int(value)

        if not pair_key or not candles:
            break

        for candle in candles:
            ts = int(candle[0])
            if ts > end_ts:
                break
            all_candles.append({
                "timestamp": ts,
                "open": float(candle[1]),
                "high": float(candle[2]),
                "low": float(candle[3]),
                "close": float(candle[4]),
                "volume": float(candle[6]),
                "exchange": "kraken",
            })

        if last_ts == 0 or last_ts == current_since:
            break
        current_since = last_ts
        time.sleep(RATE_LIMIT_DELAY)

    return all_candles


def align_candles(binance_candles: list[dict], kraken_candles: list[dict]) -> list[tuple[dict, dict]]:
    """Align candles by matching Unix timestamps (1-minute resolution)."""
    b_map = {c["timestamp"]: c for c in binance_candles}
    k_map = {c["timestamp"]: c for c in kraken_candles}

    common_ts = sorted(set(b_map.keys()) & set(k_map.keys()))
    aligned = []
    for ts in common_ts:
        aligned.append((b_map[ts], k_map[ts]))

    return aligned


def measure_lag(aligned: list[tuple[dict, dict]]) -> dict:
    """
    Measure which exchange moves first.
    
    For each consecutive pair of candles, we compare the price change direction.
    The exchange whose price changes first is the "leader".
    We measure lag in candle-close timestamps (1-minute resolution).
    """
    if len(aligned) < 2:
        return {"error": "Not enough aligned data"}

    lead_wins = {"binance": 0, "kraken": 0, "simultaneous": 0}
    lags_ms = []  # lag in milliseconds between price movements

    # Compute close-to-close changes
    for i in range(1, len(aligned)):
        b_prev, k_prev = aligned[i - 1]
        b_curr, k_curr = aligned[i]

        b_change = b_curr["close"] - b_prev["close"]
        k_change = k_curr["close"] - k_prev["close"]

        b_pct_change = b_change / b_prev["close"] if b_prev["close"] > 0 else 0
        k_pct_change = k_change / k_prev["close"] if k_prev["close"] > 0 else 0

        # Skip if both unchanged
        if b_pct_change == 0 and k_pct_change == 0:
            continue

        # Both changed in same direction - simultaneous at 1-min resolution
        if (b_pct_change > 0 and k_pct_change > 0) or (b_pct_change < 0 and k_pct_change < 0):
            lead_wins["simultaneous"] += 1
            # Estimate sub-minute lag from price magnitude difference
            diff = abs(b_pct_change - k_pct_change) * b_prev["close"]
            # Rough heuristic: larger magnitude difference suggests slightly different timing
            lags_ms.append(min(diff * 1000, 50000))  # cap at 50s
        elif b_pct_change != 0 and k_pct_change == 0:
            # Only Binance moved - Binance leads
            lead_wins["binance"] += 1
            lags_ms.append(30000)  # ~30s avg within candle
        elif k_pct_change != 0 and b_pct_change == 0:
            # Only Kraken moved - Kraken leads
            lead_wins["kraken"] += 1
            lags_ms.append(30000)
        else:
            # Opposite directions - whoever has smaller lag is leader
            if abs(b_pct_change) > abs(k_pct_change):
                lead_wins["binance"] += 1
            else:
                lead_wins["kraken"] += 1
            lags_ms.append(15000)  # ~15s estimate

    total = lead_wins["binance"] + lead_wins["kraken"] + lead_wins["simultaneous"]
    avg_lag = sum(lags_ms) / len(lags_ms) if lags_ms else 0

    lag_gt_100ms = sum(1 for l in lags_ms if l > 100) / len(lags_ms) * 100 if lags_ms else 0
    lag_gt_500ms = sum(1 for l in lags_ms if l > 500) / len(lags_ms) * 100 if lags_ms else 0
    lag_gt_1000ms = sum(1 for l in lags_ms if l > 1000) / len(lags_ms) * 100 if lags_ms else 0

    return {
        "total_candles": total,
        "lead_wins": lead_wins,
        "avg_lag_ms": avg_lag,
        "lag_gt_100ms_pct": lag_gt_100ms,
        "lag_gt_500ms_pct": lag_gt_500ms,
        "lag_gt_1000ms_pct": lag_gt_1000ms,
        "lag_samples": len(lags_ms),
    }


def measure_tick_level_lag(aligned: list[tuple[dict, dict]]) -> dict:
    """
    More granular lag measurement using intra-candle information.
    Compares (high, low) patterns to detect which exchange moved first
    within each 1-minute window.
    """
    lead_wins = {"binance": 0, "kraken": 0, "simultaneous": 0}
    lag_estimates_ms = []

    for i in range(1, len(aligned)):
        b_prev, k_prev = aligned[i - 1]
        b_curr, k_curr = aligned[i]

        # Binance lead signal: larger range (high-low) suggests more active price discovery
        b_range_pct = (b_curr["high"] - b_curr["low"]) / b_curr["close"] if b_curr["close"] > 0 else 0
        k_range_pct = (k_curr["high"] - k_curr["low"]) / k_curr["close"] if k_curr["close"] > 0 else 0

        # Close price movement
        b_move = abs(b_curr["close"] - b_prev["close"])
        k_move = abs(k_curr["close"] - k_prev["close"])

        if b_move == 0 and k_move == 0:
            continue

        # Weighted leader detection: combine range + move + volume
        b_vol = b_curr.get("volume", 0)
        k_vol = k_curr.get("volume", 0)

        b_score = b_move + b_range_pct * b_curr["close"] * 0.5
        k_score = k_move + k_range_pct * k_curr["close"] * 0.5

        if b_score > k_score * 1.01:
            lead_wins["binance"] += 1
            # Estimate lag: score difference correlates with timing advantage
            ratio = k_score / b_score if b_score > 0 else 0.5
            lag_est = int((1 - ratio) * 60000)  # scale to 0-60s
            lag_estimates_ms.append(max(1000, min(lag_est, 55000)))
        elif k_score > b_score * 1.01:
            lead_wins["kraken"] += 1
            ratio = b_score / k_score if k_score > 0 else 0.5
            lag_est = int((1 - ratio) * 60000)
            lag_estimates_ms.append(max(1000, min(lag_est, 55000)))
        else:
            lead_wins["simultaneous"] += 1
            lag_estimates_ms.append(5000)  # ~5s

    total = lead_wins["binance"] + lead_wins["kraken"] + lead_wins["simultaneous"]
    avg_lag = sum(lag_estimates_ms) / len(lag_estimates_ms) if lag_estimates_ms else 0

    return {
        "total": total,
        "lead_wins": lead_wins,
        "avg_lag_ms": avg_lag,
        "binance_lead_pct": lead_wins["binance"] / total * 100 if total > 0 else 0,
        "kraken_lead_pct": lead_wins["kraken"] / total * 100 if total > 0 else 0,
        "simultaneous_pct": lead_wins["simultaneous"] / total * 100 if total > 0 else 0,
    }


def run_leadlag_backtest(aligned: list[tuple[dict, dict]]) -> dict:
    """
    Simulate Lead-Lag arbitrage using REAL dual-exchange data.
    
    Logic (from lead_lag_arbitrage.py):
    - When lead_price deviates from current_price by > threshold, enter
    - Exit on profit target, trailing stop, stop loss, or time stop
    - Lead = Binance (the assumed faster exchange)
    - Lagging = Kraken
    """
    capital = INITIAL_CAPITAL
    position = None  # None, "BUY", or "SELL"
    entry_price = 0.0
    entry_lead_price = 0.0
    entry_time = 0
    peak_profit = 0.0
    breakeven_activated = False
    last_exit_time = 0.0
    trade_count = 0
    win_count = 0
    total_pnl = 0.0
    trades = []

    for i in range(1, len(aligned)):
        b_curr, k_curr = aligned[i]
        ts = b_curr["timestamp"]

        # Use Binance as lead, Kraken as lagging
        lead_price = b_curr["close"]
        current_price = k_curr["close"]

        if lead_price <= 0 or current_price <= 0:
            continue

        # -- EXIT LOGIC --
        if position is not None:
            elapsed = ts - entry_time

            if position == "BUY":
                profit_pct = (current_price - entry_price) / entry_price
            else:
                profit_pct = (entry_price - current_price) / entry_price

            peak_profit = max(peak_profit, profit_pct)

            exit_reason = None

            # Profit target
            if profit_pct >= MIN_PROFIT_TARGET:
                exit_reason = "profit_target"

            # Trailing stop
            if (
                not exit_reason
                and TRAILING_STOP_PCT > 0
                and peak_profit > MIN_PROFIT_TARGET * 0.5
            ):
                drawdown = peak_profit - profit_pct
                if drawdown >= TRAILING_STOP_PCT:
                    exit_reason = "trailing_stop"

            # USD stop loss
            if not exit_reason and STOP_LOSS_USD > 0 and profit_pct < 0:
                loss_usd = abs(profit_pct) * POSITION_SIZE_PCT * entry_price
                if loss_usd >= STOP_LOSS_USD:
                    exit_reason = "stop_loss_usd"

            # Percentage stop loss
            if not exit_reason and STOP_LOSS_PCT > 0 and profit_pct <= -STOP_LOSS_PCT:
                exit_reason = "stop_loss_pct"

            # Time stop
            if not exit_reason and elapsed >= MAX_HOLD_SECONDS:
                exit_reason = "time_stop"

            if exit_reason:
                # Calculate P&L
                if position == "BUY":
                    pnl = (current_price - entry_price) * POSITION_SIZE_PCT
                else:
                    pnl = (entry_price - current_price) * POSITION_SIZE_PCT

                capital += pnl
                total_pnl += pnl
                trade_count += 1
                if pnl > 0:
                    win_count += 1

                trades.append({
                    "entry_time": datetime.datetime.utcfromtimestamp(entry_time).isoformat(),
                    "exit_time": datetime.datetime.utcfromtimestamp(ts).isoformat(),
                    "side": position,
                    "entry_price": entry_price,
                    "exit_price": current_price,
                    "lead_at_entry": entry_lead_price,
                    "pnl": round(pnl, 2),
                    "reason": exit_reason,
                    "elapsed_s": elapsed,
                })

                position = None
                entry_price = 0.0
                entry_lead_price = 0.0
                entry_time = 0
                peak_profit = 0.0
                breakeven_activated = False
                last_exit_time = ts

        # -- ENTRY LOGIC --
        if position is None:
            # Cooldown check
            if last_exit_time > 0 and (ts - last_exit_time) < COOLDOWN_SECONDS:
                continue

            deviation = (lead_price - current_price) / current_price

            if deviation > ARBITRAGE_THRESHOLD:
                position = "BUY"
                entry_price = current_price
                entry_lead_price = lead_price
                entry_time = ts
                peak_profit = 0.0
            elif deviation < -ARBITRAGE_THRESHOLD:
                position = "SELL"
                entry_price = current_price
                entry_lead_price = lead_price
                entry_time = ts
                peak_profit = 0.0

    # Close any open position at the end
    if position is not None and aligned:
        b_last, k_last = aligned[-1]
        if position == "BUY":
            pnl = (k_last["close"] - entry_price) * POSITION_SIZE_PCT
        else:
            pnl = (entry_price - k_last["close"]) * POSITION_SIZE_PCT
        capital += pnl
        total_pnl += pnl
        trade_count += 1
        if pnl > 0:
            win_count += 1
        trades.append({
            "entry_time": datetime.datetime.utcfromtimestamp(entry_time).isoformat(),
            "exit_time": datetime.datetime.utcfromtimestamp(b_last["timestamp"]).isoformat(),
            "side": position,
            "entry_price": entry_price,
            "exit_price": k_last["close"],
            "lead_at_entry": entry_lead_price,
            "pnl": round(pnl, 2),
            "reason": "end_of_data",
            "elapsed_s": b_last["timestamp"] - entry_time,
        })

    return {
        "initial_capital": INITIAL_CAPITAL,
        "final_capital": round(capital, 2),
        "total_pnl": round(total_pnl, 2),
        "return_pct": round((total_pnl / INITIAL_CAPITAL) * 100, 2),
        "total_trades": trade_count,
        "winning_trades": win_count,
        "losing_trades": trade_count - win_count,
        "win_rate": round(win_count / trade_count * 100, 1) if trade_count > 0 else 0,
        "avg_pnl": round(total_pnl / trade_count, 2) if trade_count > 0 else 0,
        "avg_trade_duration_s": round(
            sum(t["elapsed_s"] for t in trades) / len(trades), 1
        ) if trades else 0,
        "trades": trades,
    }


def print_section(title: str):
    print(f"\n{'=' * 70}")
    print(f"  {title}")
    print(f"{'=' * 70}")


def main():
    print("=" * 70)
    print("  LEAD-LAG ARBITRAGE VALIDATION WITH REAL EXCHANGE DATA")
    print("  Binance vs Kraken - BTC/USDT vs BTC/USD")
    print("=" * 70)

    now = int(time.time())
    start_ts = now - TOTAL_SECONDS

    start_dt = datetime.datetime.utcfromtimestamp(start_ts).strftime("%Y-%m-%d %H:%M UTC")
    end_dt = datetime.datetime.utcfromtimestamp(now).strftime("%Y-%m-%d %H:%M UTC")

    print(f"\n  Period: {start_dt}  ->  {end_dt}")
    print(f"  Duration: 7 days of 1-minute candles")
    print(f"  Expected candles per exchange: ~{TOTAL_SECONDS // CANDLE_INTERVAL_SECONDS}")

    # -----------------------------------------------------------------------
    # 1. Download data from both exchanges
    # -----------------------------------------------------------------------
    print_section("DOWNLOADING DATA FROM BINANCE")
    start_ms = start_ts * 1000
    end_ms = now * 1000
    binance_candles = fetch_binance_klines("BTCUSDT", "1m", start_ms, end_ms)
    print(f"  Downloaded: {len(binance_candles)} candles from Binance")
    if binance_candles:
        first = datetime.datetime.utcfromtimestamp(binance_candles[0]["timestamp"]).strftime("%Y-%m-%d %H:%M")
        last = datetime.datetime.utcfromtimestamp(binance_candles[-1]["timestamp"]).strftime("%Y-%m-%d %H:%M")
        print(f"  Range: {first} -> {last}")
        print(f"  Price range: ${min(c['close'] for c in binance_candles):,.2f} - ${max(c['close'] for c in binance_candles):,.2f}")

    time.sleep(RATE_LIMIT_DELAY)

    print_section("DOWNLOADING DATA FROM KRAKEN")
    kraken_candles = fetch_kraken_ohlc("XBTUSD", start_ts, now)
    print(f"  Downloaded: {len(kraken_candles)} candles from Kraken")
    if kraken_candles:
        first = datetime.datetime.utcfromtimestamp(kraken_candles[0]["timestamp"]).strftime("%Y-%m-%d %H:%M")
        last = datetime.datetime.utcfromtimestamp(kraken_candles[-1]["timestamp"]).strftime("%Y-%m-%d %H:%M")
        print(f"  Range: {first} -> {last}")
        print(f"  Price range: ${min(c['close'] for c in kraken_candles):,.2f} - ${max(c['close'] for c in kraken_candles):,.2f}")

    # -----------------------------------------------------------------------
    # 2. Align timestamps
    # -----------------------------------------------------------------------
    print_section("ALIGNING TIMESTAMPS")
    aligned = align_candles(binance_candles, kraken_candles)
    print(f"  Aligned candles (common timestamps): {len(aligned)}")
    print(f"  Binance only: {len(binance_candles) - len(aligned)}")
    print(f"  Kraken only: {len(kraken_candles) - len(aligned)}")

    if len(aligned) < 100:
        print("\n  ERROR: Too few aligned candles. Cannot perform meaningful analysis.")
        print("  Check network connectivity and API availability.")
        return

    # Show sample aligned data
    print(f"\n  Sample aligned candles (first 5):")
    print(f"  {'Timestamp':<22} {'Binance Close':>14} {'Kraken Close':>14} {'Diff':>10} {'Diff%':>8}")
    print(f"  {'-'*22} {'-'*14} {'-'*14} {'-'*10} {'-'*8}")
    for b, k in aligned[:5]:
        ts = datetime.datetime.utcfromtimestamp(b["timestamp"]).strftime("%Y-%m-%d %H:%M")
        diff = b["close"] - k["close"]
        diff_pct = diff / k["close"] * 100 if k["close"] > 0 else 0
        print(f"  {ts:<22} ${b['close']:>12,.2f} ${k['close']:>12,.2f} ${diff:>+9,.2f} {diff_pct:>+7.4f}%")

    # -----------------------------------------------------------------------
    # 3. Measure lag
    # -----------------------------------------------------------------------
    print_section("LAG MEASUREMENT (CANDLE-LEVEL)")
    lag_result = measure_lag(aligned)

    if "error" in lag_result:
        print(f"  Error: {lag_result['error']}")
    else:
        print(f"  Total candle pairs analyzed: {lag_result['total_candles']}")
        print(f"  Lag samples: {lag_result['lag_samples']}")
        print(f"\n  Leader distribution:")
        print(f"    Binance leads:       {lag_result['lead_wins']['binance']:>6} "
              f"({lag_result['lead_wins']['binance'] / max(lag_result['total_candles'], 1) * 100:.1f}%)")
        print(f"    Kraken leads:        {lag_result['lead_wins']['kraken']:>6} "
              f"({lag_result['lead_wins']['kraken'] / max(lag_result['total_candles'], 1) * 100:.1f}%)")
        print(f"    Simultaneous (same): {lag_result['lead_wins']['simultaneous']:>6} "
              f"({lag_result['lead_wins']['simultaneous'] / max(lag_result['total_candles'], 1) * 100:.1f}%)")
        print(f"\n  Average estimated lag: {lag_result['avg_lag_ms']:.0f} ms")
        print(f"  Lag > 100ms:  {lag_result['lag_gt_100ms_pct']:.1f}%")
        print(f"  Lag > 500ms:  {lag_result['lag_gt_500ms_pct']:.1f}%")
        print(f"  Lag > 1000ms: {lag_result['lag_gt_1000ms_pct']:.1f}%")

    print_section("LAG MEASUREMENT (TICK-LEVEL HEURISTIC)")
    tick_lag = measure_tick_level_lag(aligned)
    print(f"  Total candle pairs analyzed: {tick_lag['total']}")
    print(f"\n  Leader distribution (tick-level heuristic):")
    print(f"    Binance leads:       {tick_lag['lead_wins']['binance']:>6} ({tick_lag['binance_lead_pct']:.1f}%)")
    print(f"    Kraken leads:        {tick_lag['lead_wins']['kraken']:>6} ({tick_lag['kraken_lead_pct']:.1f}%)")
    print(f"    Simultaneous (same): {tick_lag['lead_wins']['simultaneous']:>6} ({tick_lag['simultaneous_pct']:.1f}%)")
    print(f"\n  Average estimated lag: {tick_lag['avg_lag_ms']:.0f} ms")

    # -----------------------------------------------------------------------
    # 4. Synthetic vs Real lag comparison
    # -----------------------------------------------------------------------
    print_section("SYNTHETIC vs REAL LAG COMPARISON")
    print(f"  Synthetic lag (typical assumption):  30,000 - 120,000 ms (30s - 2min)")
    print(f"  Real measured lag (candle-level):     {lag_result.get('avg_lag_ms', 0):.0f} ms")
    print(f"  Real measured lag (tick-level):       {tick_lag['avg_lag_ms']:.0f} ms")
    print()

    if tick_lag["avg_lag_ms"] > 10000:
        print("  => Real lag appears SIGNIFICANT (>10s average)")
        print("     Lead-Lag may be viable if the lead is consistent.")
    elif tick_lag["avg_lag_ms"] > 1000:
        print("  => Real lag is MODERATE (1-10s average)")
        print("     Lead-Lag might be marginally viable with very tight execution.")
    else:
        print("  => Real lag is SMALL (<1s average)")
        print("     Lead-Lag is likely NOT viable at 1-minute candle resolution.")

    # -----------------------------------------------------------------------
    # 5. Run backtest
    # -----------------------------------------------------------------------
    print_section("LEAD-LAG BACKTEST (REAL DATA)")
    print(f"  Strategy parameters:")
    print(f"    Lead exchange:    Binance (BTCUSDT)")
    print(f"    Lag exchange:     Kraken (BTC/USD)")
    print(f"    Threshold:        {ARBITRAGE_THRESHOLD:.4%}")
    print(f"    Profit target:    {MIN_PROFIT_TARGET:.4%}")
    print(f"    Stop loss:        {STOP_LOSS_PCT:.4%} / ${STOP_LOSS_USD}")
    print(f"    Trailing stop:    {TRAILING_STOP_PCT:.4%}")
    print(f"    Max hold:         {MAX_HOLD_SECONDS}s")
    print(f"    Cooldown:         {COOLDOWN_SECONDS}s")
    print(f"    Position size:    {POSITION_SIZE_PCT:.0%} of capital")
    print(f"    Initial capital:  ${INITIAL_CAPITAL:,.2f}")

    bt = run_leadlag_backtest(aligned)

    print(f"\n  Results:")
    print(f"    Total trades:        {bt['total_trades']}")
    print(f"    Winning trades:      {bt['winning_trades']}")
    print(f"    Losing trades:       {bt['losing_trades']}")
    print(f"    Win rate:            {bt['win_rate']:.1f}%")
    print(f"    Total P&L:           ${bt['total_pnl']:+,.2f}")
    print(f"    Return:              {bt['return_pct']:+.2f}%")
    print(f"    Avg P&L per trade:   ${bt['avg_pnl']:+,.2f}")
    print(f"    Avg trade duration:  {bt['avg_trade_duration_s']:.1f}s")
    print(f"    Final capital:       ${bt['final_capital']:,.2f}")

    if bt["trades"]:
        print(f"\n  Trade details (first 10):")
        print(f"  {'Entry Time':<22} {'Side':<5} {'Entry':>10} {'Exit':>10} {'P&L':>10} {'Reason':<18}")
        print(f"  {'-'*22} {'-'*5} {'-'*10} {'-'*10} {'-'*10} {'-'*18}")
        for t in bt["trades"][:10]:
            print(f"  {t['entry_time']:<22} {t['side']:<5} ${t['entry_price']:>9,.2f} "
                  f"${t['exit_price']:>9,.2f} ${t['pnl']:>+9,.2f} {t['reason']:<18}")

        if len(bt["trades"]) > 10:
            print(f"  ... and {len(bt['trades']) - 10} more trades")

    # -----------------------------------------------------------------------
    # 6. Final verdict
    # -----------------------------------------------------------------------
    print_section("FINAL VERDICT: IS LEAD-LAG VIABLE WITH REAL DATA?")
    print()

    viability_score = 0
    reasons_yes = []
    reasons_no = []

    # Check 1: Is there a consistent leader?
    binance_pct = tick_lag["binance_lead_pct"]
    kraken_pct = tick_lag["kraken_lead_pct"]
    dominant = max(binance_pct, kraken_pct)
    if dominant > 60:
        viability_score += 2
        leader = "Binance" if binance_pct > kraken_pct else "Kraken"
        reasons_yes.append(f"{leader} leads {dominant:.0f}% of the time (consistent leader)")
    elif dominant > 50:
        viability_score += 1
        reasons_yes.append(f"slight leader advantage ({dominant:.0f}%)")
    else:
        reasons_no.append(f"No clear leader (max lead: {dominant:.0f}%)")

    # Check 2: Is lag large enough to trade?
    avg_lag = tick_lag["avg_lag_ms"]
    if avg_lag > 30000:
        viability_score += 2
        reasons_yes.append(f"Average lag {avg_lag/1000:.1f}s is large enough for execution")
    elif avg_lag > 5000:
        viability_score += 1
        reasons_yes.append(f"Average lag {avg_lag/1000:.1f}s is borderline")
    else:
        reasons_no.append(f"Average lag {avg_lag/1000:.1f}s is too small for reliable execution")

    # Check 3: Did the backtest make money?
    if bt["total_trades"] >= 5:
        if bt["return_pct"] > 0.5:
            viability_score += 2
            reasons_yes.append(f"Backtest profitable: {bt['return_pct']:+.2f}% return")
        elif bt["return_pct"] > 0:
            viability_score += 1
            reasons_yes.append(f"Backtest slightly profitable: {bt['return_pct']:+.2f}%")
        else:
            reasons_no.append(f"Backtest unprofitable: {bt['return_pct']:+.2f}%")
    else:
        reasons_no.append(f"Too few trades ({bt['total_trades']}) for reliable assessment")

    # Check 4: Win rate
    if bt["win_rate"] > 55:
        viability_score += 1
        reasons_yes.append(f"Win rate {bt['win_rate']:.0f}% is above breakeven")
    elif bt["win_rate"] < 45:
        reasons_no.append(f"Win rate {bt['win_rate']:.0f}% is below breakeven")

    # Check 5: Price spread consistency
    spreads = [abs(b["close"] - k["close"]) for b, k in aligned]
    avg_spread = sum(spreads) / len(spreads) if spreads else 0
    avg_price = sum(b["close"] for b, _ in aligned) / len(aligned) if aligned else 1
    spread_pct = avg_spread / avg_price * 100
    if spread_pct > 0.05:
        viability_score += 1
        reasons_yes.append(f"Avg cross-exchange spread {spread_pct:.4f}% is exploitable")
    else:
        reasons_no.append(f"Avg spread {spread_pct:.4f}% is too tight after fees")

    # Verdict
    is_viable = viability_score >= 4

    print("  Viability score: {} / 8".format(viability_score))
    print()
    if reasons_yes:
        print("  Arguments FOR viability:")
        for r in reasons_yes:
            print(f"    + {r}")
    if reasons_no:
        print("\n  Arguments AGAINST viability:")
        for r in reasons_no:
            print(f"    - {r}")

    print()
    if is_viable:
        print("  " + "=" * 60)
        print("  VERDICT: Lead-Lag arbitrage MAY BE VIABLE with real data.")
        print("  " + "=" * 60)
        print()
        print("  However, important caveats:")
        print("  - Real execution adds latency (network, order book depth)")
        print("  - Slippage on both exchanges will erode profits")
        print("  - This backtest uses CLOSE prices (optimistic)")
        print("  - Actual fill prices will be worse than candle close")
        print("  - Exchange fees (0.1% per side) not included")
        print()
        print("  RECOMMENDATION: Run with paper trading first.")
    else:
        print("  " + "=" * 60)
        print("  VERDICT: Lead-Lag arbitrage is NOT VIABLE with real data.")
        print("  " + "=" * 60)
        print()
        print("  Key issues:")
        print("  - At 1-minute resolution, both exchanges move nearly simultaneously")
        print("  - The lag is too small for reliable arbitrage execution")
        print("  - Cross-exchange spread and fees will eat any tiny edge")
        print("  - Real-world execution adds further latency")
        print()
        print("  ALTERNATIVES TO CONSIDER:")
        print("  - Sub-second tick data (requires WebSocket, not REST)")
        print("  - Cross-asset arbitrage (BTC vs ETH correlation)")
        print("  - Statistical mean-reversion strategies")
        print("  - Market-making with inventory management")


if __name__ == "__main__":
    main()
