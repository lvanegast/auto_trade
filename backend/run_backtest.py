"""
Backtest Runner — Descarga datos históricos de Binance y ejecuta estrategias de arbitraje.

Uso:
    python run_backtest.py                    # Backtest LeadLag con datos por defecto
    python run_backtest.py --strategy leadlag --days 30
    python run_backtest.py --strategy all --days 7
"""

import asyncio
import argparse
import os
import sys
import time
import threading
from datetime import datetime, timedelta, timezone

import pandas as pd
import numpy as np
import requests

# Setup path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("TRADING_MODE", "paper")
os.environ.setdefault("EXECUTION_TYPE", "simulation")

# Create a background event loop so strategies using asyncio.get_event_loop() work
_loop = asyncio.new_event_loop()
_loop_thread = threading.Thread(target=_loop.run_forever, daemon=True)
_loop_thread.start()
asyncio.set_event_loop(_loop)

# Disable security guard for backtesting
from src.core import security
security.security_guard._backtesting = True
security.security_guard._halt_all = False
security.security_guard._kill_switch = False
security.security_guard._paused_workers = set()
security.security_guard._daily_pnl = {}
security.security_guard._consecutive_losses = {}

from src.engine.backtester import BacktestEngine
from src.strategy.lead_lag_arbitrage import LeadLagArbitrageStrategy, BinanceTracker
from src.strategy.sports_arb import SportsArbitrageStrategy, update_sports_edge
from src.core import security


def fetch_binance_klines(symbol: str = "BTCUSDT", interval: str = "1m", days: int = 7) -> pd.DataFrame:
    """Fetch historical klines from Binance REST API."""
    print(f"Descargando datos de Binance: {symbol} {interval} x {days} dias...")

    end_ms = int(time.time() * 1000)
    start_ms = int((time.time() - days * 86400) * 1000)

    all_data = []
    current_start = start_ms

    while current_start < end_ms:
        url = "https://api.binance.com/api/v3/klines"
        params = {
            "symbol": symbol,
            "interval": interval,
            "startTime": current_start,
            "endTime": end_ms,
            "limit": 1000,
        }

        try:
            resp = requests.get(url, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(f"  Error fetching data: {e}")
            break

        if not data:
            break

        for candle in data:
            all_data.append({
                "timestamp": pd.to_datetime(candle[0], unit="ms", utc=True),
                "open": float(candle[1]),
                "high": float(candle[2]),
                "low": float(candle[3]),
                "close": float(candle[4]),
                "volume": float(candle[5]),
            })

        current_start = data[-1][0] + 1
        time.sleep(0.2)  # Rate limit

    df = pd.DataFrame(all_data)
    if df.empty:
        return df

    df["price"] = df["close"]
    df["bid"] = df["close"] * 0.9999  # Simulated bid-ask spread
    df["ask"] = df["close"] * 1.0001
    df = df.drop_duplicates(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)

    print(f"  Descargados {len(df)} velas ({df['timestamp'].min()} a {df['timestamp'].max()})")
    return df


def generate_synthetic_lead_lag_data(df: pd.DataFrame, lag_pct: float = 0.003) -> pd.DataFrame:
    """
    Generate lead-lag data from Binance klines.
    'price' = local exchange (lagging), 'lead_price' = Binance (leading).
    The lead price leads by a few seconds, creating arbitrage opportunities.
    """
    result = df.copy()

    # Binance price is the "lead" - use close price directly
    result["lead_price"] = result["close"]

    # Local price lags behind with autocorrelated noise (more realistic)
    noise = np.random.normal(0, lag_pct, len(result))
    # Add autocorrelation so deviations persist for a few ticks
    for i in range(1, len(noise)):
        noise[i] = noise[i] * 0.7 + noise[i-1] * 0.3
    result["price"] = result["close"] * (1 + noise)
    result["bid"] = result["price"] * 0.9999
    result["ask"] = result["price"] * 1.0001

    return result


def generate_synthetic_cross_platform_data(df: pd.DataFrame, spread_pct: float = 0.03) -> pd.DataFrame:
    """
    Generate synthetic cross-platform arb data.
    Simulates two platforms with periodic price divergences.
    """
    result = df.copy()

    n = len(result)
    base_price = result["close"].values

    # Platform A (Kalshi) tracks close price
    kalshi_price = base_price.copy()

    # Platform B (Limitless) deviates periodically
    cycle = np.sin(np.linspace(0, 8 * np.pi, n)) * spread_pct
    limitless_price = base_price * (1 + cycle + np.random.normal(0, spread_pct * 0.3, n))

    result["price"] = (kalshi_price + limitless_price) / 2
    result["bid"] = result["price"] * 0.999
    result["ask"] = result["price"] * 1.001
    result["kalshi_price"] = kalshi_price
    result["limitless_price"] = limitless_price

    return result


def run_leadlag_backtest(df: pd.DataFrame, initial_capital: float = 10000.0) -> dict:
    """Run LeadLagArbitrageStrategy backtest."""
    print("\n" + "=" * 60)
    print("BACKTEST: LeadLagArbitrageStrategy")
    print("=" * 60)

    BinanceTracker.latest_btc_price = 0.0

    strategy = LeadLagArbitrageStrategy(
        symbol="BTCUSDT",
        arbitrage_threshold=0.0010,
        min_profit_target=0.0015,
        max_hold_seconds=15.0,
        stop_loss_pct=0.005,
        trailing_stop_pct=0.0010,
        cooldown_seconds=5.0,
        position_size_pct=0.15,
        db=None,
        worker_id="backtest_leadlag",
    )

    backtester = BacktestEngine(initial_capital=initial_capital, position_size_usd=50.0)

    # Patch backtester to add debug
    original_run = backtester.run_backtest
    trade_count = [0]
    def debug_run(strat, df):
        orig_process = None
        # We'll just run and check
        result = original_run(strat, df)
        return result
    backtester.run_backtest = debug_run

    metrics = backtester.run_backtest(strategy, df)

    print(f"\nResultados LeadLag:")
    print(f"  Total Trades:    {metrics['total_trades']}")
    print(f"  Win Rate:        {metrics['win_rate_pct']:.1f}%")
    print(f"  Total PnL:       ${metrics['total_pnl_usd']:.2f}")
    print(f"  Profit Factor:   {metrics['profit_factor']:.2f}")
    print(f"  Max Drawdown:    {metrics['max_drawdown_pct']:.2f}%")
    print(f"  Sharpe Ratio:    {metrics['sharpe_ratio']:.2f}")
    print(f"  Final Capital:   ${metrics['final_capital']:.2f}")

    return metrics


def run_sports_backtest(df: pd.DataFrame, initial_capital: float = 10000.0) -> dict:
    """Run SportsArbitrageStrategy backtest with synthetic 1xN data."""
    print("\n" + "=" * 60)
    print("BACKTEST: SportsArbitrageStrategy (1xN Synthetic)")
    print("=" * 60)

    strategy = SportsArbitrageStrategy(
        symbol="SPORTS_TEST",
        feeder_type="limitless_sports",
        min_edge_pct=0.03,
        position_size_usd=50.0,
        max_hold_seconds=300.0,
        stop_loss_pct=0.10,
        cooldown_seconds=30.0,
        db=None,
        worker_id="backtest_sports",
    )

    # Generate synthetic sports data with periodic arb opportunities
    n = len(df)
    sports_prices = np.random.uniform(0.20, 0.40, n)

    sports_df = df.copy()
    sports_df["price"] = sports_prices
    sports_df["bid"] = sports_prices * 0.99
    sports_df["ask"] = sports_prices * 1.01

    # Inject arb opportunities periodically (every ~50 ticks)
    for i in range(0, n, 50):
        edge = np.random.uniform(0.04, 0.10)  # 4-10% edge
        p1 = 0.25 + np.random.uniform(-0.05, 0.05)
        p2 = 0.30 + np.random.uniform(-0.05, 0.05)
        p3 = 1.0 - p1 - p2 - edge

        if p3 > 0.05:
            update_sports_edge(
                event_id="SPORTS_TEST",
                total_yes=p1 + p2 + p3,
                edge=edge,
                outcomes_count=3,
                title="Test Sports Event",
                outcomes=[
                    {"slug": "team-a", "title": "Team A", "yes_price": p1, "no_price": round(1.0 - p1, 4)},
                    {"slug": "team-b", "title": "Team B", "yes_price": p2, "no_price": round(1.0 - p2, 4)},
                    {"slug": "team-c", "title": "Team C", "yes_price": p3, "no_price": round(1.0 - p3, 4)},
                ],
                group_slug="SPORTS_TEST",
            )

    backtester = BacktestEngine(initial_capital=initial_capital, position_size_usd=50.0)
    metrics = backtester.run_backtest(strategy, sports_df)

    print(f"\nResultados Sports Arbitrage:")
    print(f"  Total Trades:    {metrics['total_trades']}")
    print(f"  Win Rate:        {metrics['win_rate_pct']:.1f}%")
    print(f"  Total PnL:       ${metrics['total_pnl_usd']:.2f}")
    print(f"  Profit Factor:   {metrics['profit_factor']:.2f}")
    print(f"  Max Drawdown:    {metrics['max_drawdown_pct']:.2f}%")
    print(f"  Sharpe Ratio:    {metrics['sharpe_ratio']:.2f}")
    print(f"  Final Capital:   ${metrics['final_capital']:.2f}")

    return metrics


def run_parameter_sweep(df: pd.DataFrame, initial_capital: float = 10000.0):
    """Sweep LeadLag parameters to find optimal settings."""
    print("\n" + "=" * 60)
    print("PARAMETER SWEEP: LeadLagArbitrageStrategy")
    print("=" * 60)

    configs = [
        {"threshold": 0.0005, "profit_target": 0.0010, "cooldown": 1.0, "hold_time": 15.0},
        {"threshold": 0.0005, "profit_target": 0.0015, "cooldown": 1.0, "hold_time": 15.0},
        {"threshold": 0.0008, "profit_target": 0.0015, "cooldown": 1.0, "hold_time": 15.0},
        {"threshold": 0.0010, "profit_target": 0.0015, "cooldown": 1.0, "hold_time": 15.0},
        {"threshold": 0.0010, "profit_target": 0.0020, "cooldown": 1.0, "hold_time": 15.0},
        {"threshold": 0.0005, "profit_target": 0.0010, "cooldown": 1.0, "hold_time": 30.0},
        {"threshold": 0.0005, "profit_target": 0.0015, "cooldown": 1.0, "hold_time": 30.0},
        {"threshold": 0.0010, "profit_target": 0.0020, "cooldown": 2.0, "hold_time": 30.0},
        {"threshold": 0.0005, "profit_target": 0.0010, "cooldown": 1.0, "hold_time": 60.0},
        {"threshold": 0.0008, "profit_target": 0.0015, "cooldown": 2.0, "hold_time": 60.0},
    ]

    results = []

    for i, cfg in enumerate(configs):
        BinanceTracker.latest_btc_price = 0.0

        strategy = LeadLagArbitrageStrategy(
            symbol="BTCUSDT",
            arbitrage_threshold=cfg["threshold"],
            min_profit_target=cfg["profit_target"],
            max_hold_seconds=cfg["hold_time"],
            stop_loss_pct=0.005,
            trailing_stop_pct=0.0010,
            cooldown_seconds=cfg["cooldown"],
            position_size_pct=0.15,
            db=None,
            worker_id=f"sweep_{i}",
        )

        backtester = BacktestEngine(initial_capital=initial_capital, position_size_usd=50.0)
        metrics = backtester.run_backtest(strategy, df)

        results.append({
            **cfg,
            "trades": metrics["total_trades"],
            "win_rate": metrics["win_rate_pct"],
            "pnl": metrics["total_pnl_usd"],
            "profit_factor": metrics["profit_factor"],
            "sharpe": metrics["sharpe_ratio"],
            "max_dd": metrics["max_drawdown_pct"],
        })

    results.sort(key=lambda x: x["pnl"], reverse=True)

    print(f"\n{'Thresh':>8} {'TP':>8} {'CD':>5} {'Hold':>6} {'Trades':>7} {'Win%':>7} {'PnL':>10} {'PF':>6} {'Sharpe':>7} {'MaxDD':>7}")
    print("-" * 82)
    for r in results:
        print(f"{r['threshold']:>8.4f} {r['profit_target']:>8.4f} {r['cooldown']:>5.0f} {r['hold_time']:>6.0f} {r['trades']:>7} {r['win_rate']:>6.1f}% ${r['pnl']:>8.2f} {r['profit_factor']:>6.2f} {r['sharpe']:>7.2f} {r['max_dd']:>6.2f}%")

    if results:
        best = results[0]
        print(f"\nMejor configuracion:")
        print(f"  Threshold: {best['threshold']} | TP: {best['profit_target']} | Cooldown: {best['cooldown']}s | Hold: {best['hold_time']}s")
        print(f"  Trades: {best['trades']} | Win Rate: {best['win_rate']:.1f}% | PnL: ${best['pnl']:.2f}")
        print(f"  Sharpe: {best['sharpe']:.2f} | Max DD: {best['max_dd']:.2f}%")

    return results


def main():
    parser = argparse.ArgumentParser(description="Backtest Runner")
    parser.add_argument("--strategy", choices=["leadlag", "sports", "sweep", "all"], default="all")
    parser.add_argument("--days", type=int, default=7, help="Days of historical data")
    parser.add_argument("--symbol", default="BTCUSDT", help="Binance symbol")
    parser.add_argument("--capital", type=float, default=10000.0, help="Initial capital")
    args = parser.parse_args()

    print(f"{'=' * 60}")
    print(f"BACKTEST RUNNER - {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'=' * 60}")
    print(f"Estrategia: {args.strategy} | Dias: {args.days} | Symbol: {args.symbol}")
    print(f"Capital Inicial: ${args.capital:,.2f}")

    # Fetch real data from Binance
    df = fetch_binance_klines(symbol=args.symbol, interval="1m", days=args.days)
    if df.empty:
        print("ERROR: No se pudieron descargar datos. Verifica tu conexion a internet.")
        return

    all_metrics = {}

    if args.strategy in ("leadlag", "all"):
        leadlag_df = generate_synthetic_lead_lag_data(df)
        all_metrics["leadlag"] = run_leadlag_backtest(leadlag_df, args.capital)

    if args.strategy in ("sports", "all"):
        all_metrics["sports"] = run_sports_backtest(df, args.capital)

    if args.strategy in ("sweep", "all"):
        leadlag_df = generate_synthetic_lead_lag_data(df)
        all_metrics["sweep"] = run_parameter_sweep(leadlag_df, args.capital)

    # Summary
    if len(all_metrics) > 1:
        print("\n" + "=" * 60)
        print("RESUMEN COMPARATIVO")
        print("=" * 60)
        for name, m in all_metrics.items():
            if name == "sweep":
                continue
            print(f"\n{name.upper()}:")
            print(f"  Trades: {m['total_trades']} | Win: {m['win_rate_pct']:.1f}% | PnL: ${m['total_pnl_usd']:.2f} | Sharpe: {m['sharpe_ratio']:.2f}")


if __name__ == "__main__":
    main()
