# Arbitrage Research - Prediction Markets 2026

> **Fecha**: Agosto 8, 2026 (actualizado)
> **Fuentes**: arXiv papers, GitHub repos (pmxt, HarrierOnChain, radioman), PolyTest, CuteMarkets, Dune Analytics, PredictionAuthority, CF Benchmarks, Limitless Docs, Kalshi Docs, docs.polymarket.us, IBKR Campus

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
| **Cross-platform price deviation** | **2-4% average** | Gebele & Matthes (2026) |
| **Polymarket NBA arb median return** | **101 bps** | Cheng et al. (2026) |
| **Binance-Polymarket pricing gap** | **5.6-6.3 pp** | Portnaya (2026) |
| **Polymarket $40M extraído (on-chain)** | $40M | Saguillo et al. (2025) |
| **Bookmaker-vs-exchange arb (fútbol)** | 19.2% de partidos | Franck (2013) |
| **Arb sportsbook-vs-sportsbook (NBA)** | 4.52% del tiempo, ~13s | Princeton (2025) |
| **Cross-platform deviation (persistente)** | 2-4% | Gebele & Matthes (2026) |
| **Kalshi underreaction (0.64-por-1)** | drift predecible | Angelini & De Angelis (2026) |
| **Makers > Takers (Betfair)** | positivos | Whelan (2025) |

---

## Academic Research Findings (2026)

### Paper 1: Semantic Non-Fungibility in Prediction Markets (Gebele & Matthes, Jan 2026)
**arXiv:2601.01706** | [PDF](https://arxiv.org/pdf/2601.01706)

**Key findings:**
- **6% of events** are concurrently listed across multiple platforms
- **2-4% average price deviation** between semantically equivalent markets
- Mispricings are **persistent** and driven by **structural frictions**, not informational disagreement
- **Semantic non-fungibility** (different event descriptions, resolution rules) is the fundamental barrier to price convergence
- Cross-platform dataset: 100,000+ events across 10 venues (2018-2025)

**Implication for our project:** The 2-4% deviation is above our 2% minimum viable edge threshold. The key challenge is **event matching** — finding the same event across platforms with different naming conventions.

---

### Paper 2: Arbitrage Analysis in Polymarket NBA Markets (Cheng et al., Apr 2026)
**arXiv:2605.00864** | [PDF](https://arxiv.org/pdf/2605.00864)

**Key findings:**
- 75 million limit order book snapshots across 173 NBA games analyzed
- **Single-market anomalies**: Only 7 executable episodes, median duration **3.6 seconds**
- **Combinatorial inefficiencies**: 290 active episodes, concentrated in final minutes of live play
- Median return: **101 basis points** for combinatorial execution
- **76.9% of opportunities** constrained to average executable size of **14.8 shares**
- Theoretical "Middle" jackpot **never empirically realized**

**Implication for our project:** Intra-platform arb on sports exists but is **extremely rare** and **tiny size**. Cross-platform arb (our approach) is more promising because it doesn't depend on intra-platform mispricings.

---

### Paper 3: Prediction Markets vs Option Prices (Portnaya, Jun 2026)
**arXiv:2606.19517** | [PDF](https://arxiv.org/pdf/2606.19517)

**Key findings:**
- Polymarket vs Binance Bitcoin options: **5.6 percentage point** mean pricing gap
- Gap is **persistent** (AR(1) half-life ~4 hours) yet **mean-reverting**
- Largest at **low probabilities** and **long maturities**
- Delta-hedged arbitrage proxy **profitable after conservative transaction costs**
- Deribit extension: **11 percentage point** gap

**Implication for our project:** Cross-platform pricing wedges between prediction markets and traditional options are real and exploitable. Focus on markets with low implied probabilities and longer maturities.

---

### Paper 4: PolySwarm Multi-Agent Framework (Barot & Borkhatariya, Apr 2026)
**arXiv:2604.03888** | [PDF](https://arxiv.org/pdf/2604.03888)

**Key findings:**
- 50 diverse LLM personas evaluate binary outcome markets simultaneously
- **Confidence-weighted Bayesian combination** of swarm consensus with market-implied probabilities
- **Quarter-Kelly position sizing** for risk-controlled execution
- **KL/JS divergence** to detect cross-market inefficiencies and negation pair mispricings
- **Latency arbitrage module**: exploits stale prices by deriving CEX-implied probabilities
- Swarm aggregation **outperforms single-model baselines** in probability calibration

**Implication for our project:** Multi-model ensemble approach could improve our probability estimation. The latency arbitrage module (CEX-implied probabilities) could be adapted for our Binance oracle worker.

---

### Paper 5: Markets Are Not Random, They Are Hard to Predict (Noguer i Alonso, Jun 2026)

### Paper 6: Unravelling the Probabilistic Forest: Arbitrage in Prediction Markets (Saguillo et al., Oct 2025)
**AFT 2025 / arXiv:2508.03474** | [PDF](https://drops.dagstuhl.de/entities/document/10.4230/LIPIcs.AFT.2025.27)

**Key findings:**
- Dos formas de arbitraje en Polymarket: **Market Rebalancing** (intra-market, un solo condition) y **Combinatorial** (inter-market, varios conditions)
- Evidencia empírica on-chain: **~$40M de beneficio real extraído** por arbitrageurs durante el periodo medido
- Reduce el problema O(2^(n+m)) de comparar mercados relacionados con heurística (timeliness, similitud tópica, combinaciones)

**Implication for our project:** Confirma con datos de ejecución real que ambos tipos de arb existen y son explotados. El rebalancing intra-market (comprar el conjunto de outcomes < $1) es exactamente nuestro 1xN intra-platform.

---

### Paper 7: Agreeing to Disagree: The Economics of Betting Exchanges (Whelan, Sep 2025)
**CEPR DP20633** | [PDF](https://cepr.org/system/files/publication-files/DP20633.pdf)

**Key findings:**
- Análisis de >200K partidos de fútbol de Betfair (order book completo 1s, 2022-2024)
- **Los Makers (los que postean límites) ganan más que los Takers (los que aceptan)**
- Los longshots pierden sistemáticamente conforme avanza el partido (efecto "Yogi Berra"): los Takers sobreestiman las remontadas tardías
- Profits pequeños pero significativos para Takers en favoritos durante la 2ª mitad

**Implication for our project:** Valida empíricamente la estrategia maker de Limitless (0% fees + rebates): postear quotes gana más que cruzar el spread. También refuerza el Resolution Sniper: comprar favoritos (YES ~0.95-0.98) cerca del final captura la ineficiencia de los que sobrepagan remontadas.

---

### Paper 8: Inter-Market Arbitrage in Betting (Franck, 2013 — Economica)
**DOI: 10.1111/ecca.12009**

**Key findings:**
- Apostar combinado en **bookmaker + betting exchange** da retorno positivo garantizado en el **19.2%** de los partidos de las top-5 ligas europeas
- Todos los bookmakers analizados ofrecían posiciones de arbitraje frecuentemente y con márgenes negativos

**Implication for our project:** El arbitraje cruzado entre estructuras de mercado distintas (dealer vs exchange) es real y frecuente en fútbol. Sugiere que añadir un sportsbook/exchange (Betfair, Novig, ProphetX) como tercera plataforma ampliaría las oportunidades de Worker 2.

---

### Paper 9: When Do Markets Fully Process Public Information? (Angelini & De Angelis, Jun 2026)
**arXiv:2606.07811**

**Key findings:**
- Mercados NBA de Kalshi: los precios responden a información pública en la dirección correcta pero **solo 0.64-por-1** del cambio que debería ocurrir (underreaction)
- El ajuste incompleto **predice drift** en los minutos siguientes, especialmente en mercados con poca liquidez
- No es explotable neto de bid-ask, pero valida el lead-lag (Worker 5) como señal

**Implication for our project:** Los deportes en vivo tienen underreaction predecible. Un oráculo (Binance/play-by-play) + entrada en mercados de baja liquidez puede capturar drift, aunque el paper advierte que el bid-ask lo consume.

---

### Paper 10: Exploiting Arbitrage Opportunities in Live Sports Betting (Princeton Thesis, Apr 2025)
**Princeton University**

**Key findings:**
- FanDuel vs BetMGM en NBA: el arbitraje existe pero es **raro y efímero** — presente solo **4.52%** del tiempo de juego, con duración media de **~13 segundos**
- Limitaciones prácticas: bloqueos de odds, restricciones geográficas (no se puede apostar en 2 estados a la vez), riesgo de cuenta

**Implication for our project:** El arb bookmaker-vs-bookmaker es de latencia ~13s. Nuestro foco en exchanges con API pública (no sportsbooks con scrape) evita las restricciones de geolocalización y bloques de odds.

---

**arXiv:2606.08209** | [PDF](https://arxiv.org/pdf/2606.08209)

**Key findings:**
- Markets are not ontically random — they are causal systems that are hard to predict
- Positive signals need not be scalable due to capacity constraints
- The P-Q wedge relates to stochastic-discount-factor geometry
- Alpha decay occurs as private bits migrate into the market budget
- Crowding is mutual compressibility of signals

**Implication for our project:** Arbitrage opportunities decay as more participants discover them. Speed of execution matters — opportunities that exist now may not exist in minutes.

---

## Open Source Tools & Repositories

### PMXT (CCXT for Prediction Markets) — ⭐ 2.1k stars
**GitHub**: [pmxt-dev/pmxt](https://github.com/pmxt-dev/pmxt) | **Docs**: [pmxt.dev](https://pmxt.dev)

**What it is:** Unified API for prediction market data and trading across Polymarket, Kalshi, Limitless, and 10+ other venues.

**Key features:**
- Hosted API with custody, signing, and on-chain settlement
- Self-host option for venue-native credentials
- Python and TypeScript SDKs
- MCP-native (works with Claude, Cursor, AI agents)
- Drop-in Dome API replacement

**Supported venues:** Polymarket, Polymarket US, Kalshi, Limitless, Probable, Baozi, Myriad, Opinion, Metaculus, Smarkets, Hyperliquid, Gemini Titan, SuiBets, Rain, Hunch

**How to use:** `pip install pmxt` — could replace our custom feeders with a unified library.

---

### Prediction Markets Trading Bot Toolkits — ⭐ 319 stars
**GitHub**: [HarrierOnChain/Prediction-Markets-Trading-Bot-Toolkits](https://github.com/HarrierOnChain/Prediction-Markets-Trading-Bot-Toolkits)

**What it is:** Production-grade Rust trading bots with 10 strategies on one execution core.

**Strategies (most relevant to us):**
1. **Copy Trading** — Mirror wallets with proven on-chain record
2. **BTC 5m/15m/1hr Arbitrage** — Speed on short-window BTC Up/Down (~42ms end-to-end)
3. **Cross-Market Arbitrage** — Lock the spread across Polymarket ↔ Kalshi ↔ PredictIt
4. **Directional Arbitrage** — Arb base (Up + Down < $1), tilt toward side with more edge
5. **Resolution Sniper** — 95¢ near-certainty → guaranteed $1.00 payout
6. **Orderbook Imbalance** — Live OBI signal, 500ms refresh
7. **Market Making** — Two-sided GTD with inventory skew

**Safety layer:**
- Circuit Breaker: auto-halts after N consecutive large trades
- Depth Guard: validates orderbook liquidity before every order
- Dry Run: full execution path without real orders
- Trade Floor: minimum size enforcement against negative-EV micro-trades

**Venues live:** Polymarket, Kalshi, Limitless, Drift BET, Augur, Azuro, Myriad Markets

**Implication:** Their **Cross-Market Arbitrage** strategy is exactly what we're building. Their **Directional Arbitrage** (buy YES+NO basket < $1, tilt toward side with more edge) is a strategy we haven't considered.

---

### Polymarket Arbitrage Bot — ⭐ 493 stars
**GitHub**: [radioman/polymarket-arbitrage-trading-bot](https://github.com/radioman/polymarket-arbitrage-trading-bot)

**What it is:** BTC and ETH 5-minute prediction market arbitrage bot with automated execution.

**Strategies implemented:**
- `btc_momentum` — Follow BTC vs price-to-beat
- `odds_favorite` — Follow market favorite
- `btc_and_odds` — Both must agree
- `btc_or_odds` — Either signal suffices
- `contrarian` — Fade extremes
- `btc_mean_revert` — Bet snap-back before close

**Key config parameters:**
- `minBtcDeltaUsd: 20` — Min BTC move for signal
- `minFavoriteOddsPct: 72` — Min market agreement
- `maxEntryOddsPct: 95` — Max buy price
- `maxBetsPerWindow: 1` — One trade per 5m window

**Implication:** Their `contrarian` and `btc_mean_revert` strategies are interesting for our Limitless crypto workers. The `contrarian` strategy (fade extremes) could work when one side is extremely overpriced.

## Actionable Strategies from Research

### Strategy 1: Cross-Platform Semantic Matching (HIGH PRIORITY)
**Source:** Gebele & Matthes (2026)

**How it works:**
1. Fetch events from Limitless and Kalshi
2. Use semantic similarity (NLP) to match events across platforms
3. Compare YES_ask on Platform A vs NO_ask on Platform B
4. Execute when `cost < $1.00 - fees` and edge > 2%

**Expected edge:** 2-4% based on academic findings
**Challenge:** Event matching accuracy, capital pre-funding on both platforms

---

### Strategy 2: Resolution Sniper (MEDIUM PRIORITY)
**Source:** HarrierOnChain

**How it works:**
1. Scan for near-certainty contracts (95¢+) where market has effectively resolved
2. Buy at 95¢, hold to $1.00 payout
3. High win-rate, low per-trade return — compounds on volume

**Expected edge:** 5% per trade (buy at 95¢, receive $1.00)
**Challenge:** Identifying truly resolved markets before they settle

---

### Strategy 3: Directional Arbitrage (MEDIUM PRIORITY)
**Source:** HarrierOnChain

**How it works:**
1. Buy YES + NO basket when total < $1.00 (structural arb base)
2. Tilt extra size toward the side with more edge (higher probability)
3. Limit-only, hedged base

**Expected edge:** 1-3% on base + directional alpha
**Challenge:** Requires both sides to be available simultaneously

---

### Strategy 4: Multi-Agent Probability Estimation (LOW PRIORITY)
**Source:** PolySwarm (Barot & Borkhatariya, 2026)

**How it works:**
1. Deploy multiple LLM personas to evaluate binary markets
2. Aggregate estimates via confidence-weighted Bayesian combination
3. Compare consensus with market-implied probabilities
4. Trade when divergence exceeds threshold

**Expected edge:** 2-5% when swarm disagrees with market
**Challenge:** Computational cost, model calibration

---

### Strategy 5: Orderbook Imbalance Signal (LOW PRIORITY)
**Source:** HarrierOnChain

**How it works:**
1. Monitor live orderbook bid/ask depth skew
2. Use as short-term directional signal
3. Refresh every 500ms

**Expected edge:** Predicts short-term price movement
**Challenge:** Requires high-frequency data, latency-sensitive

---

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

## Polymarket US (QCX/AEC) — DEPORTES MATCH-LEVEL (Agosto 2026)

> **ACTUALIZACIÓN CRÍTICA**: Nuestra conclusión anterior de que "Polymarket no tiene mercados match-level para ligas US" quedó **OBSOLETA** (dic 2025).

### Estado

- **Polymarket US** (QCX LLC / Aristotle Exchange Clearing, CFTC DCM) lanzado **dic-2025**, catálogo sports-first.
- Volumen junio-2026: **$3.04B** (Polymarket internacional: $10.26B).
- Deportes con **partidos individuales** (match-level) y API pública:
  **NFL, NBA, MLB, NHL, MLS, UFC, CBB, CFB, UCL, EPL, ATP, WTA**.
- Tipos de mercado por partido: **Moneyline, Spread, Total, Props** (+ en MLB first-5/first-inning, sub-periodos NBA, etc.).
- **Mismo settlement source** que Limitless (proveedores Sportradar/Stats Perform, feeds oficiales) → candidato real para Worker 2.

### API (documentada en docs.polymarket.us)

| Endpoint | Uso |
|---|---|
| `GET https://gateway.polymarket.us/v2/leagues/{nfl,nba,mlb,...}/events?active=true&closed=false` | Eventos con partidos y markets |
| `GET https://gateway.polymarket.us/v1/sports/teams?filters.league=nfl` | Teams/leagues |
| `POST https://api.preprod.polymarketexchange.com/v1/refdata/instruments` | Instrumentos (estado OPEN, series) |
| CLOB `/book` | Orderbooks |

- **Metadatos clave por instrumento** (NO parsear symbol/slug — no es contrato público):
  - `event_id` — slug canónico del partido, **compartido por todos los markets del juego** (nuestro matcheo ideal)
  - `event_external_id_sportradar` — game ID de Sportradar
  - `market_sport_type` — identifica el tipo (ej. `_team_full_game_winner`)
  - `outcome_strike` — línea/handicap
  - `long_participant_id` / `short_participant_id` — equipos canónicos
- **Verificado**: `gateway.polymarket.us/v2/leagues/nfl/events` responde **HTTP 200** desde nuestro entorno (sin bloqueo 403, a diferencia de Polymarket.com).

### Implicación

- Reabre **Worker 2 (cross-platform sports)**: Limitless vs Polymarket US sobre los MISMOS partidos (mismo settlement).
- Kalshi también lista deportes match-level (NFL/NBA/MLB) → **triangulación a 3 plataformas** para el mismo partido.
- El `event_id` compartido de Polymarket US resuelve parte del problema de matcheo semántico.

---

## Plataformas con API pública (no cubiertas previamente)

| Plataforma | Tipo | Settlement | API | Notas |
|---|---|---|---|---|
| **Polymarket US (AEC/QCX)** | DCM CFTC | USD | gateway.polymarket.us, refdata, CLOB | **Deportes match-level** (ver arriba) |
| **Robinhood Event Contracts** | Distribuidor | USD | vía Kalshi | Ruta al book de Kalshi |
| **IBKR Prediction Markets** | Broker | USD | Web API + Python TWS | Unifica **Kalshi + CME + ForecastEx** |
| **ForecastEx** | DCM CFTC (NYSE) | USD | IBKR CPAPI/TWS | Macro/econ; **cupón 3.13% APY** sobre posiciones |
| **CME Event Contracts** | DCM | USD | IBKR | Diarios sobre futuros |
| **Novig** | Sports exchange P2P | USD | API (verificar) | Sin vig; $75M Series B feb-2026 |
| **ProphetX** | Sports exchange | USD | API (verificar) | Limit-order, sharp-friendly |
| **Drift Bet** | On-chain (Solana) | USDC | API | — |
| **OG.com** | Esports | USD/crypto | API (verificar) | — |

### ForecastEx / CME vía IBKR (detalles)

- Descubrimiento: `GET https://api.ibkr.com/v1/api/iserver/secdef/search?symbol=FF` → conid → `secdef/strikes` → `secdef/info` (pares Call/Yes y Put/No).
- Market data: `/iserver/marketdata/snapshot` y websocket.
- **ForecastEx no se puede vender (solo comprar)**; para salir se compra el opuesto y IBKR netea. CME sí se compra y vende.
- Fees: más competitivo en posiciones grandes.

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

### Real (Agosto 2026, verificada en `/api/workers` de producción)

| Worker | Name | Symbol | Feeder | Strategy | Purpose |
|--------|------|--------|--------|----------|---------|
| **Worker 2** | Cross-Platform Sports | `SPORTS` | `multi_platform` | `CrossPlatformArbitrageStrategy` | Limitless vs Kalshi (multi_platform feeder) |
| **Worker 3** | Limitless Sports (3 Opciones) | `SPORTS` | `limitless_sports` | `SportsArbitrageStrategy` | Sports arb 3-outcome intra-platform |
| **Worker 4** | Limitless Sports Maker | `SPORTS` | (maker) | `maker_making` / MarketMaking | Postear quotes 0% fees |
| **Worker 5** | Binance HFT Oracle | `BTCUSDT` | `binance` | `LeadLagArbitrageStrategy` | Binance spot como oráculo lead-lag |
| **Worker 7** | Resolution Sniper | — | — | `ResolutionSniperStrategy` | Comprar YES ~0.95-0.98 pre-settlement |

> **Nota**: La config de template (`pure_arbitrage`, 6 workers) NO coincide con producción. No existen Worker 1 ni Worker 6 en el despliegue real. `ALLOWED_REAL_WORKERS` vacío → todos en observación (sin ejecución real).

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

- [ ] **Implementar feeder de Polymarket US (gateway.polymarket.us) para Worker 2** — ya responde HTTP 200; matcheo por `event_id` compartido
- [ ] Verificar que `limitless_ws_feeder` sobrevive el cambio de auth HMAC (`lmts-api-key`/`lmts-timestamp`/`lmts-signature`) — la API key estática está deprecada
- [ ] Fix AtomicCryptoArbStrategy (bid/ask confusion) — solo si se reactiva w6
- [ ] Clean up phantom positions en worker_6 (si aplica)

### Short-term

- [ ] Triangular **Limitless + Kalshi + Polymarket US** para el mismo partido (mismo settlement) en Worker 2
- [ ] Evaluar IBKR/ForecastEx como tercera fuente para macro (cupón 3.13% APY sobre posiciones)
- [ ] Monitorizar Novig / ProphetX / Robinhood Event Contracts cuando abran API estable

### Long-term

- [ ] Explorar arb combinatorio intra-market (Saguillo: rebalancing + combinatorial) sobre el catálogo de Limitless
- [ ] Estudiar maker rewards de Limitless para postear quotes (Whelan: makers > takers)
- [ ] Backtesting con eventos reales de 2026 (Homerun: ventana de fill ±2s)

---

## References

- PolyTest: https://www.polytest.io/docs/guides/how-to-backtest-prediction-markets
- CuteMarkets: https://cutemarkets.com/docs/backtesting-execution-realism
- PredictionAuthority: https://predictionauthority.com/strategy/how-to-arbitrage-polymarket-kalshi/
- Limitless Docs: https://docs.limitless.exchange/
- Kalshi Docs: https://kalshi.com/
- CF Benchmarks: https://www.cfbenchmarks.com/data/indices/BRTI
- Dune Analytics: https://dune.com/blog/polymarket-fast-markets
- Polymarket US docs: https://docs.polymarket.us/ (gateway.polymarket.us, v1/sports, refdata)
- IBKR Prediction Markets (Kalshi/CME/ForecastEx): https://www.interactivebrokers.com/campus/
- Saguillo et al. (2025): https://drops.dagstuhl.de/entities/document/10.4230/LIPIcs.AFT.2025.27
- Whelan (2025) CEPR DP20633: https://cepr.org/publications/dp20633
- Franck (2013): https://onlinelibrary.wiley.com/doi/10.1111/ecca.12009
- Angelini & De Angelis (2026): https://arxiv.org/abs/2606.07811
- Princeton (2025): https://www.princeton.edu/
