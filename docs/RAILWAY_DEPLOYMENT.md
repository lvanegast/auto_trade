# Railway Deployment Plan

## Services

1. Use Railway PostgreSQL. Do not deploy `db_trading` from `docker-compose.yml`.
2. Deploy one backend service using `backend/Dockerfile` and `railway.toml`.
3. Deploy a separate monitor service from the same image with start command `/app/monitor-entrypoint.sh`.

The monitor only writes `edge_snapshots`; it never starts the trading engine.

## Required Variables

### Runtime

`PORT`, `AUTO_START=false`, `EXECUTION_TYPE=limitless`, `TRADING_MODE=paper`, `FEEDER_TYPE=alpaca`, `TRADING_SYMBOL=BTC/USD`, `WORKER_PROFILE_MODE=pure_arbitrage`, `API_AUTH_TOKEN`.

### Database

`DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` from Railway PostgreSQL references.

### Platform Secrets

`LIMITLESS_API_KEY`, `LIMITLESS_API_SECRET`, `LIMITLESS_PRIVATE_KEY`, `KALSHI_API_KEY_ID`, `KALSHI_ENV=prod`, `KALSHI_PRIVATE_KEY_B64`.

`KALSHI_PRIVATE_KEY_B64` is decoded to `/app/arb.pem` by the entrypoint. No local Windows path is used.

### Worker Flags

`WORKER1_ENABLED=false`, `WORKER2_ENABLED=true`, `WORKER2_FEEDER_TYPE=multi_platform`, `WORKER2_SYMBOL=SPORTS`, `WORKER3_ENABLED=false`, `WORKER4_ENABLED=true`, `WORKER5_ENABLED=true`, `WORKER6_ENABLED=false`, `WORKER7_ENABLED=true`.

Worker 2 and Worker 7 are observation-only. Worker 4 is the only worker with a real execution path, and starts stopped because `AUTO_START=false`.

### Strategy and Safety Variables

Configure the current `.env` values for `SPORTS_*`, `SNIPER_*`, `ORACLE_*`, `CRYPTO_*`, `CROSS_ARB_*`, `MM_*`, `MIN_*`, `MAX_*`, `STOP_LOSS_*`, `TAKE_PROFIT_PCT`, `TRAILING_STOP_PCT`, `COOLDOWN_*`, `NEGRISK_*`, and `LIMITLESS_USE_WEBSOCKET`.

## Public Access

`X-Confirm-Action` remains required by the existing control endpoints. When `API_AUTH_TOKEN` is set, mutation endpoints additionally require `Authorization: Bearer <token>`:

- `/api/start`
- `/api/stop`
- `/api/order`
- `/api/order/cancel`
- `/api/position/close`

Do not expose the dashboard publicly without `API_AUTH_TOKEN`. Replace wildcard CORS with the deployed dashboard origin before production use.

## Post-Deploy Checks

1. `GET /api/workers` must show all workers with `is_running=false` immediately after deploy.
2. Start only the explicitly authorized workers using both authentication and `X-Confirm-Action: true`.
3. Confirm Worker 2 and Worker 7 observation logs contain `No order generated`.
4. Confirm `external_order_id` remains empty for observation workers.
5. Confirm Worker 2's execution guard rejects any injected signal before exchange calls.
