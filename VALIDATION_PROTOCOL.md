# Paper Trading Validation Protocol

## Objective
Validate all trading strategies in paper mode before committing real capital.

## Phase 1: Paper Trading (Weeks 1-4)

### Minimum Requirements Before Going Live

| Metric | Minimum | Target |
|---|---|---|
| Total trades | >= 100 | >= 200 |
| Days running | >= 14 | >= 21 |
| Win rate | >= 55% | >= 60% |
| Profit factor | >= 1.3 | >= 1.8 |
| Max drawdown | < 5% | < 3% |
| Expectancy | > 0 | > $0.50/trade |
| Sharpe ratio | > 1.0 | > 1.5 |
| Consecutive losses | < 8 | < 5 |

### Worker-Specific Targets

#### Worker 1: Lead-Lag Arbitrage (Binance → Alpaca)
- Target: 5-10 trades/day during volatile periods
- Max hold: 15 seconds
- Expected edge: 0.10-0.20% per trade
- Monitor: Binance staleness, slippage, fill rates

#### Worker 2: Cross-Platform (Kalshi ↔ Limitless)
- Target: 1-3 trades/day
- Min edge: 3%
- Expected edge: 3-8% per trade
- Monitor: Price staleness across platforms, execution latency

#### Worker 3: Sports (Limitless Intra-Platform)
- Target: 0-2 trades/day (event-driven)
- Min edge: 3%
- Monitor: Outcome sum accuracy, liquidity depth

### Daily Checklist

```
[ ] Bot running since >= 4 hours
[ ] No SecurityGuard halts triggered
[ ] All feeders connected (no stale prices)
[ ] Trades logged with correct trading_mode=paper
[ ] No errors in logs
[ ] P&L summary reviewed
[ ] Equity curve checked for anomalies
[ ] Export CSV for records
```

### Weekly Review

```
[ ] Run /api/pnl/summary with start_date=7 days ago
[ ] Compare win rate vs minimum threshold
[ ] Check profit factor
[ ] Review worst 5 trades for pattern
[ ] Review best 5 trades for replicability
[ ] Check max drawdown
[ ] Update this checklist with notes
```

## Phase 2: Limited Real Money (Weeks 5-8)

### Prerequisites
- [ ] Phase 1 metrics met for 2+ consecutive weeks
- [ ] Security Guards configured with conservative limits
- [ ] Emergency stop tested manually
- [ ] Wallet funded with minimum capital

### Rules
1. Start with 25% of intended position size
2. Max daily loss: $25 (half of paper limit)
3. Max drawdown: 3%
4. Run for 7 days before increasing size
5. If any single trade loses > 2% of capital, pause and review

### Escalation
```
Week 5-6: 25% position size → observe
Week 7-8: 50% position size → if metrics hold
Week 9+:  100% position size → full deployment
```

## Phase 3: Full Deployment (Week 9+)

### Go-Live Checklist
- [ ] All Phase 1 + Phase 2 metrics met
- [ ] Emergency stop tested and working
- [ ] SecurityGuard configured with production limits
- [ ] Wallet funded with full capital
- [ ] Monitoring alerts configured (if available)

### Ongoing Monitoring
- Review daily P&L summary every morning
- Export CSV weekly for accounting
- Monthly full audit of all positions

## Red Flags (Stop Trading Immediately)

1. **3 consecutive losses** → SecurityGuard auto-pauses, review before resuming
2. **Daily loss > $50** → Trading halted automatically
3. **Drawdown > 5% from peak** → Emergency stop triggered
4. **Stale prices > 30s** → Feeder disconnected, check connection
5. **Win rate drops below 45%** → Strategy may be broken, pause and investigate
6. **Unusual trade frequency** → More than 50 trades/hour may indicate a bug

## Emergency Procedures

### Manual Emergency Stop
```
POST /api/emergency-stop
```
This will:
- Stop all workers
- Close all open positions
- Activate kill switch
- Log CRITICAL event

### Recovery
```
POST /api/release-stop
POST /api/unpause-worker/{worker_id}
```
Then verify bot is healthy before resuming.
