# Arbitrage Research - Prediction Markets 2026

> **Fecha**: Julio 26, 2026
> **Fuentes**: PolyTest, CuteMarkets, Dune Analytics, PredictionAuthority, CF Benchmarks, Limitless Docs, Kalshi Docs

---

## Executive Summary

### Realistic Profit Expectations

| Metric | Value | Source |
|--------|-------|--------|
| **Net margin after fees** | **1-2%** | predictionauthority.com |
| **Minimum viable edge** | **>2%** | Research consensus |
| **Capital recommended** | $50K+ split across platforms | polycopy.app |
| **Opportunity duration** | Seconds to minutes | predictionauthority.com |
| **Top arbitrageur profits** | $40M+ in 12 months (Polymarket) | on-chain data |
| **Wallets with >$1K profit** | Only 0.51% | Gate/PANews report |

---

## Platform Comparison

### Fee Structures

| Platform | Maker | Taker | Notes |
|----------|-------|-------|-------|
| **Limitless** | 0% + rebates | 0.40%-3.00% (dynamic curve) | Highest near $0.50 |
| **Polymarket** | ~0% | ~1.80% (crypto) | USDC on Polygon |
| **Kalshi** | ~0% | ~0.70% | USD, CFTC-regulated |

### Settlement Sources (CRITICAL FOR ARB)

| Platform | Timeframe | Settlement Source | Oracle |
|----------|-----------|-------------------|--------|
| **Kalshi** | All (15-min to yearly) | **CF Benchmarks BRTI** (60-sec avg) | Centralized index |
| **Polymarket** | Hourly/Daily | **CF Benchmarks BRTI** | Centralized index |
| **Polymarket** | 5-min/15-min | **Binance BTC/USDT 1-min candle** | Binance direct |
| **Limitless** | 5-min/15-min/hourly | **Pyth oracle** | On-chain oracle |

### Key Insight: Cross-Platform Crypto Arb is NOT Viable

**Limitless CANNOT be arbed against Kalshi or Polymarket for crypto temporal markets** because:
- Different oracle sources → different settlement prices
- Same event, same underlying crypto, but different "price" definitions
- An arb that looks profitable could resolve as a loss

**Only viable cross-platform crypto arb**: Kalshi vs Polymarket for hourly/daily markets (both use BRTI). But:
- Fees (1-2% per platform) eat most gaps
- Both platforms are efficient — big gaps close in seconds
- Capital must be pre-funded on both platforms

---

## Cross-Platform Sports Arbitrage (VIABLE)

### Why Sports Works

Sports events have:
- **Same settlement source** across platforms (official sports data)
- **Longer opportunity windows** (hours/days vs seconds)
- **Multiple outcomes** (1xN) creating natural arb spreads
- **Different user bases** → different pricing efficiency

### Known Opportunities

| Event Type | Typical Spread | Example |
|------------|----------------|---------|
| **Football (Soccer)** | 2-5 cents | Win/Loss/Draw across platforms |
| **Tennis** | 1-3 cents | Match winner |
| **Basketball** | 2-4 cents | Game winner, spreads |
| **MMA/UFC** | 3-6 cents | Fight winner |

### Strategy: 1xN Binary Outcome Arbitrage

For events with N outcomes:
1. Fetch odds from Platform A and Platform B
2. Calculate: `cost = YES_ask_platformA + NO_ask_platformB`
3. If `cost < $1.00 - fees`, execute arb
4. Guaranteed profit = `$1.00 - cost`

---

## Crypto Temporal Markets (Limitless)

### Market Types

| Timeframe | Duration | Notes |
|-----------|----------|-------|
| **5-min** | 5 minutes | Launched Feb 2026, highest volume |
| **15-min** | 15 minutes | Launched Sep 2025 |
| **Hourly** | 1 hour | Lower volume |
| **Daily** | 24 hours | Most stable |

### Volume Data (Polymarket)

- 5-min markets peaked at **$385M/week** (March 2026)
- 15-min markets peaked at **$292M/week** (Feb 2026)
- Fast markets = **80%+ of crypto volume** by March 2026
- **Bot concentration**: 5-min markets have highest bot activity

### Why Pure Arb Doesn't Work on Limitless

1. **YES_ask + NO_ask always ≥ $1.00 for takers** (spread + fees)
2. **Maker strategy possible** but no guarantee of fill
3. **Wide spreads** (2-5 cents) indicate less efficient markets
4. **Single platform** — no second platform with same oracle to arb against

---

## Backtesting Frameworks

### PolyTest

- **URL**: https://www.polytest.io
- **Approach**: Event-by-event simulation with orderbook-aware fills
- **Key Insight**: "Past odds ≠ past prices" — reconstruct from historical probability distributions
- **Fill Simulation**: Model queue position, walk book level-by-level

### CuteMarkets

- **URL**: https://cutemarkets.com
- **Focus**: Execution realism — reject trades when spread too wide or depth insufficient
- **Key Metric**: Realistic fill rate vs theoretical signals

### Homerun (Academic)

- **Approach**: ML model for optimal execution timing
- **Key Finding**: Best fill probability within ±2 seconds of signal

---

## Project Worker Configuration

### Current: `pure_arbitrage` Profile (6 Workers)

| Worker | Name | Symbol | Feeder | Strategy | Purpose |
|--------|------|--------|--------|----------|---------|
| **Worker 1** | Crypto Spot-Arb HFT | `BTC-INTRADAY` | `limitless` | `PolymarketSpotArbStrategy` | Crypto binary option spot arb on Limitless |
| **Worker 2** | Cross-Platform Sports | `SPORTS` | `limitless_sports` | `SportsArbitrageStrategy` | Cross-platform sports arb (Limitless vs others) |
| **Worker 3** | Limitless Sports (3 Opciones) | `SPORTS` | `limitless_sports` | `SportsArbitrageStrategy` | Sports arb on 3-outcome events |
| **Worker 4** | Limitless Sports (2 Opciones) | `SPORTS` | `limitless_sports` | `SportsArbitrageStrategy` | Sports arb on 2-outcome events |
| **Worker 5** | Binance HFT Oracle | `BTCUSDT` | `binance` | `LeadLagArbitrageStrategy` | Binance spot price as HFT reference oracle |
| **Worker 6** | Crypto Atomic-Arb | `BTC-INTRADAY` | `limitless` | `AtomicCryptoArbStrategy` | Atomic multicall/bundle arb on Base L2 |

### Strategy Assignment Logic

| Feeder Type | Default Strategy |
|-------------|------------------|
| `kalshi`, `polymarket`, `limitless` | `CrossPlatformArbitrageStrategy` |
| `limitless_sports` | `SportsArbitrageStrategy` |
| `binary_arb` | `OracleMomentumStrategy` |
| `maker_making` | `MarketMakingStrategy` |
| Other (`alpaca`, `binance`, etc.) | `LeadLagArbitrageStrategy` |

---

## Lessons Learned

### What WORKS

1. **Sports cross-platform arb** — Different platforms, same settlement, real spreads
2. **Maker strategies** — 0% fees + rebates on Limitless
3. **Lead-lag detection** — Using Binance as reference oracle for Limitless

### What DOESN'T WORK

1. **Crypto intra-platform arb** — YES_ask + NO_ask always ≥ $1.00 for takers
2. **Crypto cross-platform arb** — Different oracle sources (Pyth vs BRTI vs Binance)
3. **AtomicCryptoArbStrategy** — Uses bid_yes as buy cost (should be ask_yes)
4. **Latency arbitrage** — Not our focus, different project type

### What to Watch

1. **Kalshi vs Polymarket hourly/daily** — Same BRTI source, potential arb
2. **Limitless maker rewards** — 0% fees could enable profitable market making
3. **New platform launches** — More platforms = more arb opportunities
4. **Sports market expansion** — More events = more cross-platform arb

---

## Action Items

### Immediate

- [ ] Fix AtomicCryptoArbStrategy (bid/ask confusion)
- [ ] Clean up phantom positions in worker_6
- [ ] Verify sports arb fills are realistic

### Short-term

- [ ] Implement orderbook depth fetching from Limitless API
- [ ] Add realistic fill simulation (walk the book)
- [ ] Reject trades when spread too wide or insufficient depth

### Long-term

- [ ] Add Kalshi integration for hourly/daily crypto arb
- [ ] Expand sports arb to more platforms
- [ ] Build cross-platform arb scanner for sports events

---

## References

- PolyTest: https://www.polytest.io/docs/guides/how-to-backtest-prediction-markets
- CuteMarkets: https://cutemarkets.com/docs/backtesting-execution-realism
- PredictionAuthority: https://predictionauthority.com/strategy/how-to-arbitrage-polymarket-kalshi/
- Limitless Docs: https://docs.limitless.exchange/
- Kalshi Docs: https://kalshi.com/
- CF Benchmarks: https://www.cfbenchmarks.com/data/indices/BRTI
- Dune Analytics: https://dune.com/blog/polymarket-fast-markets
