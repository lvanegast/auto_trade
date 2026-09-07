# AGENTS.md

> **ESTE PROYECTO ES EXCLUSIVAMENTE DE ARBITRAJE PURO (1xN, Cross-Platform, HFT).**
> **NO es un bot de trading direccional, market making, ni latency arbitrage.**
> **Toda estrategia debe ser rentable SOLO si compra todos los outcomes de un evento binario por menos de $1.00 y recibe exactamente $1.00 al settlement. Si no cumple esto, no pertenece al proyecto.**
>
> **REGLA ABSOLUTA: NUNCA USAR SIMULACIÓN.** `EXECUTION_TYPE` NUNCA debe ser `simulation`. Todas las trades deben ser REALES (on-chain o API demo de la plataforma). Si una plataforma no tiene demo/testnet, se usan fondos reales. La simulación no contempla latencia, slippage, rechazos ni comportamiento real del exchange.
>
> **REGLA DE SEGURIDAD Y PROTECCIÓN DE CAPITAL (`ALLOWED_REAL_WORKERS`):** Todos los workers nuevos o activos permanecen bloqueados en modo solo recolección de datos (`observation_only=True`) por defecto. NINGÚN worker puede ejecutar órdenes ni gastar capital real a menos que su `worker_id` sea agregado explícitamente a la variable de entorno `ALLOWED_REAL_WORKERS` en `.env` (ej. `ALLOWED_REAL_WORKERS=worker_4`). Esta regla es una defensa en profundidad obligatoria en 2 capas (a nivel de Estrategia `observation_only` y a nivel de Motor `supervisor.py:_execute_order`).

## Quick Start

```bash
uv sync                        # install deps (preferred over pip)
docker-compose up -d           # start PostgreSQL (required)
python main.py                 # runs backend + frontend on :8080
```

Dashboard: http://localhost:8080 | API docs: http://localhost:8080/docs

## Commands

There is **no test suite, linter, formatter, or typecheck** configured. Do not attempt to run `pytest`, `ruff`, `mypy`, etc.

## Gotchas

- **`trading_bot.db`** in repo root is a stale SQLite artifact. The app uses PostgreSQL exclusively. Ignore/delete it.
- **Portfolio is append-only**: never `UPDATE` rows in `portfolio_state`. Always `INSERT` and read with `DISTINCT ON (asset) ... ORDER BY asset, timestamp DESC`.
- **Worker isolation**: every DB method accepts `worker_id`. Trades, portfolio, and logs are all scoped per worker.
- **Bot starts OFFLINE** (`bot_running = false`). User must press "Start" in the dashboard. `AUTO_START` env var overrides this.
- **StaticFiles mount order in `src/api.py`**: the `app.mount("/", ...)` for the frontend must come AFTER all `/api/*` routes, otherwise it shadows them.
- **BinanceWebSocket is not a feeder**. `BinanceTracker` is a static singleton used by `LeadLagArbitrageStrategy` — the `BinanceFeeder` uses WebSocket (`@bookTicker` stream) for real-time bid/ask.
- **Price history cap**: strategies keep at most 1000 ticks in memory (rolling deque/DataFrame).
- **Multi-worker config**: `WORKER1_SYMBOL`, `WORKER1_FEEDER_TYPE`, etc. Defaults to single worker using `FEEDER_TYPE`/`TRADING_SYMBOL`.
- **Worker profiles**: Set `WORKER_PROFILE_MODE` to `pure_arbitrage` (6 workers), `crypto_hft_volatile` (4 workers), or default (env-driven).
- **IG Feeder threading**: Lightstreamer runs in a separate thread; uses `asyncio.run_coroutine_threadsafe()` to push events into the asyncio Queue.
- **Limitless WebSocket**: Set `LIMITLESS_USE_WEBSOCKET=true` to use WebSocket instead of polling for crypto workers (reduces latency, avoids Cloudflare rate limits).

## Architecture

Entry point: `main.py` → uvicorn → `src/api.py` (FastAPI)

```
src/api.py          FastAPI app, singletons (db, engine)
src/engine.py       TradingEngine → N × TradingWorker (each has own Queue)
src/database.py     DatabaseManager (psycopg2, no connection pool)
src/events.py       PriceUpdateEvent, SignalEvent, OrderEvent
src/feeders/        BaseFeeder subclasses — one per broker
src/strategy/       BaseStrategy subclasses; primary: LeadLagArbitrageStrategy
web/                Static frontend (HTML/JS/CSS), mounted at /
```

Event flow: Feeder → `PriceUpdateEvent` → Queue → `TradingWorker._process_events()` → Strategy → `SignalEvent` → Queue → `_execute_order()` → DB insert

## Conventions

- All config lives in `.env` (gitignored); `.env.template` is the reference.
- Schema migrations: `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` in `init_db()`.
- Feeders must implement `async start()` / `async stop()` and call `self.queue.put(PriceUpdateEvent(...))`.
- `SignalEvent.amount` is optional; when null the engine uses the strategy-determined size.
- `SignalEvent.position_id` links a trade to the `positions` table. Strategy sets it on entry/exit.
- Execution type (`EXECUTION_TYPE`): `alpaca` (real API), `limitless` (real on-chain), `kalshi` (real/demo API). NUNCA `simulation`.
- **Positions table** is append-friendly: open positions have `status='OPEN'`, closed get `status='CLOSED'` with P&L. Strategy writes to it on entry/exit.
- **Trades ↔ Positions**: `trades.position_id` links each trade execution to its position. Strategy passes `_position_id` through `SignalEvent.position_id` on every signal.
- **Stop-loss** is configurable via `STOP_LOSS_PCT` env var (0 = disabled). Take-profit via `TAKE_PROFIT_PCT`.
- **Frontend positions panel**: Tab "Posiciones" with sub-tabs (Abiertas/Cerradas/Historial). Open positions show real-time P&L computed from `lastPrice` vs entry. Close button calls `POST /api/position/close`.
- **`datetime` import in `engine.py`**: Uses `import datetime` (module), so call `datetime.datetime.now()` not `datetime.now()`.

## New Modules (August 2026)

### LatencyTracker (`src/engine/latency_tracker.py`)
- Mide latencia real de cada llamada API a orderbooks
- Almacena p50, p95, p99 por plataforma
- Endpoint: `GET /api/latency/realtime`
- Cada feeder cronometra sus llamadas automáticamente

### OrderBookWalker (`src/engine/orderbook_walker.py`)
- Simula fills caminando el order book real nivel por nivel
- Consume liquidez según tamaño de posición
- Calcula slippage real vs mejor precio
- Detecta fills parciales (book sin suficiente liquidez)

### LimitlessWebSocketFeeder (`src/feeders/limitless_ws_feeder.py`)
- Usa WebSocket en vez de polling para mercados crypto
- Reduce latencia y evita rate limiting de Cloudflare
- Activar con `LIMITLESS_USE_WEBSOCKET=true` en `.env`

## API Endpoints

| Endpoint | Descripción |
|---|---|
| `GET /api/status` | Estado del worker activo |
| `GET /api/workers` | Lista de todos los workers |
| `GET /api/latency` | Latencia de ejecución de trades |
| `GET /api/latency/realtime` | Latencia real de API calls (nuevo) |
| `GET /api/trades` | Historial de trades |
| `GET /api/positions` | Posiciones abiertas/cerradas |
| `GET /api/arbitrage` | Oportunidades de arbitraje detectadas |
| `GET /api/sports` | Eventos deportivos monitoreados en tiempo real (desde `_sports_edge_data`) |
| `GET /api/observation/performance` | **Paper PnL** de oportunidades en observación (sin trades reales), filtrable por `category=sports|crypto` |
| `POST /api/position/close` | Cerrar posición manualmente |

## Despliegue Permanente en NVIDIA Jetson Nano & CI/CD (Septiembre 2026)

- **Servidor Físico**: NVIDIA Jetson Nano 4GB ARM64 (`192.168.10.12`).
  - Backend: `http://192.168.10.12:8080`
  - PostgreSQL: `192.168.10.12:5432` (Alpine 16, persistente en `pgdata_trading`).
- **Resiliencia de Energía**: Contenedores configurados con `restart: unless-stopped` en `docker-compose.yml`. Si la Jetson se reinicia o sufre un microcorte eléctrico, el stack de base de datos y bot se levanta automáticamente.
- **CI/CD Auto-Deploy**: Servicio nativo `bot-autodeploy.service` gestionado por `systemd`. Consulta `git fetch` cada 30 segundos; si detecta un nuevo commit en `feat/executable-arbitrage-engine`, ejecuta `git pull` y `docker restart trading_bot_backend` de forma desatendida. Cero consumo adicional de memoria RAM. Ver [`docs/JETSON_DEPLOYMENT.md`](docs/JETSON_DEPLOYMENT.md).

## Sub-salas (Deportes vs Crypto)

- **Dashboard**: selector de sala (Todos/Deportes/Crypto) en el panel Arbitraje filtra `market_prices` y oportunidades por `category`.
- **Telegram**: `TELEGRAM_CHAT_ID_SPORTS` y `TELEGRAM_CHAT_ID_CRYPTO` enrutan oportunidades y resoluciones a chats dedicados (fallback: `TELEGRAM_CHAT_ID`). Las estrategias pasan `category="sports"|"crypto"` a `send_opportunity`/`send_opportunity_resolution`.
- **Paper PnL**: `get_observation_performance()` en `connection.py` calcula PnL hipotético desde `edge_snapshots` (entry_price + resolución real): 1xN garantizado (payout $1.00 o $(N-1)) vs direccional (sniper YES). Asume fills a precio de book, no descuenta gas/fees (friction va por `friction_guard`). Sirve para medir la DETECCIÓN, no la ejecución.
- Las oportunidades se etiquetan con `category` (sports/crypto), `direction` (BUY_ALL_YES_1XN/BUY_ALL_NO_1XN/SNIPER_YES) y `outcomes_count` al registrarse en `edge_snapshots`.

## Bugs Corregidos (Agosto 2026)

### Bugs Críticos Corregidos

1. **Precios falsos de Polymarket** (`sports_arb.py`): Eliminado hash-based offset. Ahora usa solo datos reales del CrossPlatformTracker.
2. **ForecastEx hardcoded** (`forecastex_feeder.py`): Eliminados precios 0.52/0.515/0.525. Ahora rechaza si no hay conexión IBKR.
3. **Simulación silenciosa** (`execution_engine.py`): `_execute_real_trades` ahora rechaza en vez de simular.
4. **Precios Kalshi fabricados** (`kalshi_feeder.py`): Eliminada fabricación desde Limitless. Ahora skip si la API falla.
5. **Reverts aleatorios** (`atomic_crypto_arb.py`): Eliminado 15% de reverts inyectados.
6. **EXECUTION_TYPE default** (`config.py`): Cambiado de `simulation` a `limitless`.

### Mejoras Implementadas

- **Medición de latencia real**: Cada feeder cronometra sus llamadas API
- **Simulación realista**: OrderBookWalker camina el book real
- **WebSocket feeder**: Para crypto workers (evita polling)
- **Logging diferenciado**: fail_no_liquidity vs fail_timeout vs fail_rate_limited

## Mejoras y Correcciones (Septiembre 2026)

1. **Alerta Telegram en Worker 6 y Worker 1 (`maker_two_leg_strategy.py`)**: Conectado `telegram_bot.send_opportunity()` con detalle de patas (YES/NO bid, profundidades en USD, costo total y margen neto). Anteriormente solo guardaba en PostgreSQL `edge_snapshots` sin emitir aviso a Telegram.
2. **Reinicio de Resiliencia en Contenedores (`docker-compose.yml`)**: Añadido `restart: unless-stopped` a `trading_bot_db` y `trading_bot_backend` para arranque automático tras cortes de energía o reinicios en hardware físico (Jetson Nano).
3. **CI/CD Desatendido en Jetson Nano (`bot-autodeploy.service`)**: Daemon en bash (`auto_deploy.sh`) integrado en `systemd` que consulta `git fetch` cada 30 segundos, sincroniza cambios y reinicia el backend sin necesidad de interacción manual por SSH. Cero consumo de RAM adicional. Documentado en `docs/JETSON_DEPLOYMENT.md`.
4. **Arbitraje Combinatorio con Programación Lineal (`backend/src/strategy/combinatorial_arb.py`)**: Solver Dual Simplex puro en Python (cero dependencias C/scipy para máxima portabilidad en ARM64 Jetson Nano). Resuelve la canasta óptima de cobertura $\min c^T x$ sujeto a $A x \ge \mathbf{1}, x \ge 0$ sobre sub-mercados correlacionados (Tenis: Moneyline + 3+ sets; Esports Bo3: Match + Map 1 + Map 2; Fútbol: 3-way + Over/Under 2.5 + BTTS). Integrado directamente en `LimitlessSportsFeeder` con alertas Telegram en Topic 2 (Deportes).
5. **Protección contra Adverse Selection / Flujo Tóxico (`BinanceTracker.detect_jump`)**: Detección de saltos bruscos en el precio de referencia spot (>15 bps en <500ms). Pausa inmediatamente las posturas pasivas de los creadores de mercado (`MakerTwoLegStrategy` en Worker 6 y `MakerLiquidityRewardsStrategy` en Worker 1) para evitar ser ejecutados por arbitrajistas de latencia.
6. **Expansión de Sub-mercados en Resolution Sniper (`resolution_sniper_feeder.py`)**: Ahora itera por todos los sub-mercados (`for sub in subs:`) en lugar de limitarse a `subs[0]`. Monitorea simultáneamente Moneyline, sets, games y mapas en zona pre-settlement [0.975, 0.98].
7. **Motor de Order Flow Imbalance (OFI) (`backend/src/engine/order_flow_imbalance.py`)**: Mide el desbalance de volumen en la punta del libro ($\Delta Q_{bid} - \Delta Q_{ask}$) en el stream `@bookTicker` de Binance. Detecta regímenes de presión compradora/vendedora (`BULLISH_PRESSURE` / `BEARISH_PRESSURE`) para filtrar falsos breakouts en `LeadLagArbitrageStrategy` (Worker 1).
8. **Expansión de Polymarket US Gateway y Chunking SX Bet (`backend/src/feeders/multi_platform_feeder.py`)**: Añadido soporte para mercados `drawable_outcome` (Fútbol 3-way de Premier League, Champions y MLS en Polymarket US) en Worker 2. Solucionado el error `HTTP 400 Bad Request` en SX Bet fragmentando las consultas de orderbooks en lotes de 10 hashes.

## Resolution Sniper (Worker 7 CRYPTO + Worker 8 SPORTS) — Extensión a Deportes (Agosto 2026)

- **Patrón evaluado**: comprar YES/NO a `entry ∈ [0.975, 0.98]` pre-settlement y mantener hasta resolución (payout $1.00 si gana, pérdida total si no).
- **Instrumentos SEPARADOS por worker** (no mezclar en el mismo feeder):
  - **Worker 7** (`WORKER7_SYMBOL=CRYPTO`): escanea solo la página crypto up/down (`_parse_expiration` por patrón del slug).
  - **Worker 8** (`WORKER8_SYMBOL=SPORTS`): escanea solo `/sport` + `/esports` (`expiration_timestamp` real en ms).
  - El feeder `ResolutionSniperFeeder` recibe `scope="crypto"|"sports"` derivado del symbol del worker. Cada worker tiene su propio lock/scan-time por instancia.
- **Categoría**: las oportunidades se etiquetan `category="sports"|"crypto"` para enrutar al chat correcto de Telegram y filtrar el Paper PnL por sala.
- **Protecciones (idénticas)**: `observation_only=True` a nivel de estrategia, la estrategia **nunca** emite `SignalEvent` (estructuralmente read-only), y `ALLOWED_REAL_WORKERS` vacío bloquea `_execute_order` en el motor. Solo recolección de datos.
- **Monitor global de resoluciones**: solo corre en UN worker (`SNIPER_RESOLUTION_MONITOR_WORKER`, default `worker_8`) para no duplicar mensajes de Telegram; cada worker resuelve sus propias posiciones.
- **Umbral temporal deportes**: `SNIPER_SPORTS_MAX_SECONDS_TO_RESOLUTION` (default 14400s = 4h) — la casi-certeza deportiva aparece en los minutos/horas finales del partido; crypto usa `SNIPER_MAX_SECONDS_TO_RESOLUTION` (1800s).
- **Sub-mercados cubiertos**: Evalúa todos los sub-mercados de un evento (moneyline, sets, totals, handicaps). Cuando un favorito lidera con margen amplio, los sub-mercados se vuelven elegibles para captura segura pre-settlement.

### Advertencia estadística (obligatoria al interpretar el Paper PnL)

**"No ha fallado todavía" ≠ "no va a fallar".** El sniper es asimétrico: gana ~2-2.5% por trade (payout $1.00 − entry ~0.975-0.98) pero pierde ~97-98% en una sola pérdida (se pierde el principal completo). El break-even WR ≈ entry_price (≈0.975-0.98). Una racha de 29-30 wins con edge promedio ~1% es **exactamente lo esperado** antes de la primera pérdida grande, NO evidencia de rentabilidad a largo plazo. Una sola pérdida al precio típico borra ~40-100 victorias de ~1-2.5%. **Se requieren varios cientos de muestras resueltas** (no 29-30) para una conclusión estadísticamente válida, tanto en crypto como en deportes. El reporte `/api/observation/performance` incluye esta advertencia en `summary.statistical_caveat`.

## Research Findings (Julio 2026)

### Realistic Profit Expectations

- **Net margin after fees**: 1-2% (predictionauthority.com)
- **Minimum viable edge**: **>2%** required for profitability
- **Opportunity duration**: Seconds to minutes for HFT, hours/days for sports

### What's Viable

| Strategy | Viability | Notes |
|----------|-----------|-------|
| **Sports cross-platform arb** | ✅ VIABLE | Same settlement source, real spreads, 1xN outcomes |
| **Maker strategies** | ✅ VIABLE | 0% fees + rebates on Limitless |
| **Lead-lag detection** | ✅ VIABLE | Binance as reference oracle for Limitless |

### What's NOT Viable

| Strategy | Viability | Notes |
|----------|-----------|-------|
| **Crypto intra-platform arb** | ❌ NOT VIABLE | YES_ask + NO_ask always ≥ $1.00 for takers |
| **Crypto cross-platform arb** | ❌ NOT VIABLE | Different oracle sources (Pyth vs BRTI vs Binance) |

### Worker Configuration

| Worker | Purpose | Feeder | Focus |
|--------|---------|--------|-------|
| Worker 2 | Cross-Platform Sports | `multi_platform` | Limitless vs Kalshi (Polymarket US: pendiente) |
| Worker 3 | Sports 3 Options | `limitless_sports` | 1xN intra-platform |
| Worker 4 | Sports Maker | `maker_making` | Market making 0% fees |
| Worker 5 | Binance Oracle | `binance` | Reference price feed (lead-lag) |
| Worker 7 | Resolution Sniper Crypto | `resolution_sniper` | Crypto up/down: comprar YES ~0.975-0.98 pre-settlement (observación) |
| Worker 8 | Resolution Sniper Sports | `resolution_sniper` | Sports + esports: comprar YES ~0.975-0.98 pre-settlement (observación) |

### Cross-Platform Sports vs Crypto

- **Sports**: Same settlement source across platforms → real arb opportunities
- **Crypto**: Different oracle sources (Pyth/BRTI/Binance) → no true arb possible
- **Focus**: Sports workers (2-4) are the primary arb opportunity

## Environment Variables

```bash
# Core
EXECUTION_TYPE=limitless          # NUNCA 'simulation'
WORKER_PROFILE_MODE=pure_arbitrage

# Limitless
LIMITLESS_API_KEY=...
LIMITLESS_API_SECRET=...
LIMITLESS_PRIVATE_KEY=...
LIMITLESS_USE_WEBSOCKET=true      # Usar WebSocket para crypto workers

# Kalshi
KALSHI_API_KEY_ID=...
KALSHI_PRIVATE_KEY_PATH=...
KALSHI_ENV=demo                   # 'demo' para sandbox

# Workers
WORKER1_ENABLED=true
WORKER2_ENABLED=true
WORKER3_ENABLED=true
WORKER4_ENABLED=true
WORKER5_ENABLED=true
WORKER6_ENABLED=true

# Resolution Sniper (Worker 7 = crypto, Worker 8 = sports — instrumentos separados)
WORKER7_ENABLED=true
WORKER7_SYMBOL=CRYPTO
WORKER8_ENABLED=true
WORKER8_SYMBOL=SPORTS
SNIPER_MIN_ENTRY_PRICE=0.975
SNIPER_MAX_ENTRY_PRICE=0.98
SNIPER_SPORTS_MAX_SECONDS_TO_RESOLUTION=14400
SNIPER_RESOLUTION_MONITOR_WORKER=worker_8
```

## Cross-Platform Arbitrage Research (August 2026)

### Executive Summary

Cross-platform arbitrage entre Limitless y Polymarket **era** inviable con Polymarket.com (championship futures, sin partidos). Desde **dic-2025, Polymarket US (QCX/Aristotle Exchange Clearing, CFTC DCM) lista deportes match-level** (NFL, NBA, MLB, NHL, MLS, UFC, CBB, CFB, UCL, EPL, ATP, WTA) con API pública en `gateway.polymarket.us` (verificado: responde HTTP 200 desde nuestro entorno). Esto **reabre Worker 2** y permite triangulación **Limitless + Kalshi + Polymarket US** sobre los mismos partidos (mismo settlement source).

### Market Types by Platform

| Platform | Market Type | Example | Liquidity |
|----------|-------------|---------|-----------|
| **Limitless** | Match-level (specific games) | "Jessica Pegula vs Alexandra Eala" | $50K-$500K |
| **Limitless** | Match props (O/U, both to score) | "Benfica vs Heart Of Midlothian: 3+ goals" | $50K-$500K |
| **Polymarket.com** | Championship futures | "Will PSG win 2026-27 Champions League?" | $100K-$4.6M |
| **Polymarket US (AEC)** | **Match-level sports** (moneyline/spread/total/props) | "NFL GB @ PIT moneyline" | $100K+ |
| **Kalshi** | Match-level sports (2026) | "Will Team X beat the spread?" | creciente |
| **Polymarket.com** | Tennis ITF / Cricket T20 match-level | "Miroshnichenko vs Chang" | <$10K |

### Why Cross-Platform Arb With Polymarket.com Failed

1. **No market overlap** en Polymarket.com: Limitless vende match props; Polymarket.com vendía championship futures.
2. **Different market granularity**: match vs season.
3. **Polymarket.com match-level era low-liquidity** (tennis ITF, cricket T20): spreads de 1-99%.
4. **NFL/NBA/NHL**: Polymarket.com tenía 0 match-level para ligas mayores.

### Por qué cambió la ecuación (Polymarket US, dic-2025)

- Polymarket US opera bajo QCX/AEC (DCM CFTC), catálogo sports-first, volumen junio-2026 **$3.04B**.
- Lista **partidos individuales** con moneyline/spread/total/props → **mismo settlement source** que Limitless (Sportradar/Stats Perform).
- **Matcheo por `event_id` compartido** en todos los markets de un juego + `event_external_id_sportradar` → resuelve el problema de matching semántico.
- Endpoints: `GET https://gateway.polymarket.us/v2/leagues/{nfl,nba,mlb,...}/events?active=true&closed=false`, `v1/sports/teams`, refdata instruments (`POST https://api.preprod.polymarketexchange.com/v1/refdata/instruments`), CLOB `/book`.

### Price Verification (CLOB vs Gamma API)

The CLOB `/book` endpoint and Gamma API `bestBid`/`bestAsk` return the **same prices**. The earlier confusion was caused by misinterpreting the raw orderbook:

- CLOB `/book` shows ALL orders (bids at 0.01, asks at 0.99 are just lower/higher-priced orders in the book)
- CLOB `/price` shows the BEST executable price (matches Gamma API)
- For NegRisk markets, use Gamma API `bestBid`/`bestAsk` or CLOB `/price` endpoint

### Formula for NO Price

```
NO_ask = 1.0 - YES_bid
NO_bid = 1.0 - YES_ask
```

Example (PSG Champions League):
- YES_bid = 0.14, YES_ask = 0.15
- NO_ask = 1.0 - 0.14 = 0.86
- NO_bid = 1.0 - 0.15 = 0.85

### Edge Calculation for Cross-Platform Arb

```
Edge = 1.0 - (Limitless YES_ask + Polymarket NO_ask)
Edge = 1.0 - (Limitless YES_ask + (1.0 - Polymarket YES_bid))
```

Minimum edge for viability (with 0.25% friction): ≥2.25%

### Research Highlights (2025-2026)

- **$40M extraído** en Polymarket por arbitrageurs (Saguillo et al. 2025, AFT).
- **76.9% de oportunidades** de arb combinatorio NBA limitadas a ~15 shares (Cheng et al. 2026) → el tamaño importa.
- **Makers > Takers** en Betfair (Whelan 2025) → respalda estrategia maker en Limitless (0% fees + rebates).
- **Kalshi underreaction 0.64-por-1** con drift predecible (Angelini & De Angelis 2026).
- Kalshi (2026): $31.5B volumen jun-2026; Robinhood Event Contracts rutean a Kalshi; IBKR unifica Kalshi+CME+ForecastEx (ForecastEx paga cupón ~3.13% APY, no vendible).

### What Would Make Cross-Platform Arb Viable (estado)

1. ✅ **Polymarket US abrió match-level para ligas mayores** (dic-2025) — hecho
2. ⬜ Limitless abre championship futures — no relevante ya
3. ⬜ Una tercera plataforma que unifique — Kalshi ya lista match-level (parcial)
4. ✅ Ambas plataformas amplían catálogos para solaparse — en curso

### Recommendation

- **Worker 2 (cross-platform)**: **REACTIVAR** con feeder de Polymarket US (gateway.polymarket.us) + `multi_platform` (Kalshi) + Limitless. Prioridad máxima.
- **Worker 4 (maker)**: seguir como foco para capital pequeño (0% fees).
- **Triangulación**: Limitless + Kalshi + Polymarket US sobre el mismo partido (mismo settlement).

## Skills Disponibles

| Skill | Descripción | Uso |
|-------|-------------|-----|
| `trading-manager` | Líder del equipo de workers. Monitorea estado, PnL, oportunidades. | Usar SIEMPRE que el usuario pregunte por el bot, workers, trades, rendimiento. |
| `arbitrage_expert` | Experto cuantitativo en arbitraje puro. | Análisis de edge, friction, estrategias. |
| `webapp-testing` | Testing del frontend con Playwright. | Verificar funcionalidad del dashboard. |
| `code-review` | Revisión de código automatizada. | Revisar cambios antes de commits. |
| `python-lsp` | Type checking con Pyright. | Verificar tipos en código Python. |
| `frontend-design` | Diseño UI distintivo. | Mejorar estética del dashboard. |
| `skill-creator` | Crear nuevas skills. | Documentar workflows repetitivos. |
| `git_commit` | Commits semánticos. | Commits con mensajes descriptivos. |

## Codebase Memory MCP (codebase-memory-mcp)

Servidor MCP local (single static binary, tree-sitter → grafo de conocimiento persistente en SQLite) que reduce tokens en consultas estructurales del código. Instalado y configurado como MCP de OpenCode (`codebase-memory-mcp` en `~/.config/opencode/opencode.jsonc`).

- **Binario**: `C:/Users/User/.local/bin/codebase-memory-mcp.exe` (v0.9.0)
- **Datos**: `~/.cache/codebase-memory-mcp/` (grafo por proyecto)
- **Artifact compartible**: `.codebase-memory/graph.db.zst` en el repo (gitignored — se regenera con `cli index_repository`)
- **Auto-index**: habilitado (`auto_index true`); reindexa con `cli index_repository --repo-path <raíz> --mode moderate`
- **Nota**: el modo `full` crashea en este repo (worker muere en algún archivo); usar `moderate`.
- **15 herramientas MCP**: `search_graph`, `query_graph`, `trace_path`, `get_architecture`, `get_code_snippet`, `detect_changes`, etc. Consultas estructurales (definiciones, callers/callees, importaciones) deben ir al grafo antes que a greps masivos.
- Requiere reiniciar OpenCode para cargar el MCP en sesiones nuevas.

## Reference

See `CLAUDE.md` for detailed architecture docs. See `docs/ARCHITECTURE.md` for design decisions (ADRs). See `docs/ARBITRAGE_RESEARCH.md` for full research findings.
