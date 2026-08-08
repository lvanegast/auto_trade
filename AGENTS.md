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
| `POST /api/position/close` | Cerrar posición manualmente |

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
| Worker 1 | Crypto Intraday HFT | `limitless_ws` | Limitless crypto binaries |
| Worker 2 | Cross-Platform Sports | `limitless_sports` | Limitless vs Kalshi sports arb |
| Worker 3 | Sports 3 Options | `limitless_sports` | 1xN intra-platform |
| Worker 4 | Sports 2 Options | `limitless_sports` | Binary intra-platform |
| Worker 5 | Binance Oracle | `binance` | Reference price feed |
| Worker 6 | Crypto Atomic-Arb | `limitless_ws` | Limitless crypto binaries |

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
```

## Cross-Platform Arbitrage Research (August 2026)

### Executive Summary

Cross-platform arbitrage between Limitless and Polymarket is **NOT viable** with the current market structure. The two platforms sell fundamentally different market types with zero overlap.

### Market Types by Platform

| Platform | Market Type | Example | Liquidity |
|----------|-------------|---------|-----------|
| **Limitless** | Match-level (specific games) | "Jessica Pegula vs Alexandra Eala" | $50K-$500K |
| **Limitless** | Match props (O/U, both to score) | "Benfica vs Heart Of Midlothian: 3+ goals" | $50K-$500K |
| **Polymarket** | Championship futures | "Will PSG win 2026-27 Champions League?" | $100K-$4.6M |
| **Polymarket** | Season-long props | "Will LeBron retire before next season?" | $100K-$1M |
| **Polymarket** | Tennis ITF match-level | "Miroshnichenko vs Chang" | <$10K |
| **Polymarket** | Cricket T20 match-level | "Afghanistan vs Sri Lanka" | <$10K |

### Why Cross-Platform Arb Failed

1. **No market overlap**: Limitless sells soccer/esports match props; Polymarket sells championship futures. Zero markets exist on both platforms.

2. **Different market granularity**:
   - Limitless: "Benfica vs Heart Of Midlothian: 3+ total goals?" (specific match)
   - Polymarket: "Will Benfica win 2026-27 Champions League?" (season outcome)

3. **Polymarket match-level markets are low-liquidity**: The few match-level markets Polymarket has (tennis ITF, cricket T20) have spreads of 1-99%, making arb impossible.

4. **NFL/NBA/NHL**: Polymarket has 0 match-level markets for major US sports leagues. All markets are championship futures or season-long props.

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

### What Would Make Cross-Platform Arb Viable

1. Polymarket opens match-level markets for major leagues (NFL, NBA, soccer)
2. Limitless opens championship futures markets
3. A third platform bridges both market types
4. Both platforms expand their catalogs to include overlapping markets

### Recommendation

- **Worker 2 (cross-platform)**: Permanently disabled until market overlap exists
- **Worker 4 (intra-platform)**: Primary focus for $10 initial capital
- **Future monitoring**: Check periodically if platforms expand their catalogs

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
