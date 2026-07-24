"""
Backtesting Engine — evalúa el rendimiento histórico de estrategias con métricas financieras:
- Total Return (%)
- Win Rate (%)
- Profit Factor
- Sharpe Ratio
- Max Drawdown (%)
"""

import pandas as pd
import numpy as np
from typing import List, Dict, Any
from src.events import PriceUpdateEvent, SignalEvent


class BacktestEngine:
    def __init__(self, initial_capital: float = 1000.0, position_size_usd: float = 50.0):
        self.initial_capital = initial_capital
        self.capital = initial_capital
        self.position_size_usd = position_size_usd
        self.trades: List[Dict[str, Any]] = []
        self.equity_curve: List[float] = [initial_capital]

    def run_backtest(self, strategy, price_series: pd.DataFrame) -> Dict[str, Any]:
        """
        Ejecuta el backtest sobre un DataFrame con columnas ['timestamp', 'price', 'bid', 'ask'].
        """
        self.capital = self.initial_capital
        self.trades = []
        self.equity_curve = [self.initial_capital]
        open_position = None

        for _, row in price_series.iterrows():
            timestamp = row['timestamp']
            price = float(row['price'])
            bid = float(row.get('bid', price))
            ask = float(row.get('ask', price))

            event = PriceUpdateEvent(symbol=strategy.symbol, price=price, bid=bid, ask=ask)
            if hasattr(event, 'timestamp'):
                event.timestamp = pd.to_datetime(timestamp)

            # Sincronizar Tracker Dual Cross-Platform (Plataforma A vs Plataforma B)
            if hasattr(strategy, "_tracker"):
                p_kalshi = float(row.get('kalshi_price', price))
                p_limitless = float(row.get('limitless_price', price * (1 + np.random.uniform(-0.04, 0.04))))
                strategy._tracker.update_price(strategy.symbol, "kalshi", price=p_kalshi, bid=p_kalshi*0.99, ask=p_kalshi*1.01)
                strategy._tracker.update_price(strategy.symbol, "limitless", price=p_limitless, bid=p_limitless*0.99, ask=p_limitless*1.01)

            # Sincronizar Sports Edge 1xN si la estrategia es de deportes
            if hasattr(strategy, "feeder_type") and strategy.feeder_type == "limitless_sports":
                from src.strategy.sports_arb import update_sports_edge
                p1 = float(row.get('outcome_1', price))
                p2 = float(row.get('outcome_2', price * 0.8))
                p3 = float(row.get('outcome_3', 0.20))
                tot_yes = p1 + p2 + p3
                edge = 1.0 - tot_yes
                update_sports_edge(
                    event_id=strategy.symbol,
                    total_yes=tot_yes,
                    edge=edge,
                    outcomes_count=3,
                    title="Evento Deportivo Sincronizado",
                    outcomes=[
                        {"slug": "opt-1", "title": "Opción A", "yes_price": p1, "no_price": round(1.0 - p1, 4)},
                        {"slug": "opt-2", "title": "Opción B", "yes_price": p2, "no_price": round(1.0 - p2, 4)},
                        {"slug": "opt-3", "title": "Opción C", "yes_price": p3, "no_price": round(1.0 - p3, 4)},
                    ],
                    group_slug=strategy.symbol
                )

            # Actualizar tracker líder si la estrategia requiere Binance (Lead-Lag)
            if "BTC" in strategy.symbol:
                try:
                    from src.feeders.binance_feeder import BinanceTracker
                    lead_price = float(row.get('lead_price', price * (1 + np.random.uniform(-0.005, 0.005))))
                    BinanceTracker.latest_btc_price = lead_price
                except Exception:
                    pass

            signal = strategy.on_price_update(event)

            # Procesar entrada / salida simulada
            if signal:
                if signal.side == "BUY" and not open_position:
                    entry_price = ask
                    amount = signal.amount or (self.position_size_usd / entry_price if entry_price > 0 else 0)
                    cost = amount * entry_price
                    if self.capital >= cost:
                        self.capital -= cost
                        open_position = {
                            "entry_time": timestamp,
                            "entry_price": entry_price,
                            "amount": amount,
                            "cost": cost,
                            "reason": signal.reason,
                            "position_id": signal.position_id
                        }
                elif signal.side == "SELL" and open_position:
                    exit_price = bid
                    revenue = open_position["amount"] * exit_price
                    pnl = revenue - open_position["cost"]
                    pnl_pct = (pnl / open_position["cost"]) if open_position["cost"] > 0 else 0

                    self.capital += revenue
                    self.trades.append({
                        "entry_time": open_position["entry_time"],
                        "exit_time": timestamp,
                        "entry_price": open_position["entry_price"],
                        "exit_price": exit_price,
                        "amount": open_position["amount"],
                        "pnl": pnl,
                        "pnl_pct": pnl_pct,
                        "reason": open_position["reason"]
                    })
                    open_position = None

            self.equity_curve.append(self.capital + (open_position["amount"] * bid if open_position else 0))

        return self.calculate_metrics()

    def calculate_metrics(self) -> Dict[str, Any]:
        """Calcula métricas clave de desempeño."""
        if not self.trades:
            return {
                "total_trades": 0,
                "win_rate_pct": 0.0,
                "total_pnl_usd": 0.0,
                "profit_factor": 0.0,
                "max_drawdown_pct": 0.0,
                "sharpe_ratio": 0.0,
                "final_capital": self.capital
            }

        df_trades = pd.DataFrame(self.trades)
        wins = df_trades[df_trades["pnl"] > 0]
        losses = df_trades[df_trades["pnl"] < 0]

        win_rate = (len(wins) / len(df_trades)) * 100.0 if len(df_trades) > 0 else 0.0
        total_pnl = df_trades["pnl"].sum()

        gross_profit = wins["pnl"].sum() if not wins.empty else 0.0
        gross_loss = abs(losses["pnl"].sum()) if not losses.empty else 0.0
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (gross_profit if gross_profit > 0 else 0.0)

        # Drawdown máximo
        equity_series = pd.Series(self.equity_curve)
        peak = equity_series.cummax()
        drawdown = (equity_series - peak) / peak
        max_drawdown = abs(drawdown.min()) * 100.0

        # Sharpe Ratio simplificado
        returns = pd.Series(self.equity_curve).pct_change().dropna()
        sharpe = (returns.mean() / returns.std() * np.sqrt(252)) if len(returns) > 1 and returns.std() > 0 else 0.0

        return {
            "total_trades": len(df_trades),
            "winning_trades": len(wins),
            "losing_trades": len(losses),
            "win_rate_pct": round(win_rate, 2),
            "total_pnl_usd": round(total_pnl, 2),
            "gross_profit_usd": round(gross_profit, 2),
            "gross_loss_usd": round(gross_loss, 2),
            "profit_factor": round(profit_factor, 2),
            "max_drawdown_pct": round(max_drawdown, 2),
            "sharpe_ratio": round(sharpe, 2),
            "final_capital": round(self.capital, 2)
        }
