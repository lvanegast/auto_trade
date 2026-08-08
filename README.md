# 🤖 Auto Trade — Bot de Arbitraje Cuantitativo Event-Driven (Multi-Worker 24/7)

> Sistema de trading cuantitativo desacoplado para mercados de predicción y activos digitales (Limitless Exchange en Base L2, Kalshi, Alpaca y Binance Spot Oracle). Arquitectura event-driven multi-trabajador en Docker con el objetivo estricto de **rentabilidad neta >2.0% por operación** mediante **Arbitraje Puro Libre de Riesgo (Cobertura 100% $1 \times N$)** y ejecución **Post-Only Maker (0% Comisiones)**.

---

## 🎯 NORTE DEL PROYECTO & REGLAS DE ORO

> [!IMPORTANT]
> **OBJETIVO DE RENTABILIDAD:** Lograr un retorno neto **>2.0% libre de comisiones por operación**.
> **GESTIÓN DE CAPITAL PEQUEÑO:** 
> * Posiciones de **$1.00 a $3.00 USD por canasta** para no bloquear saldo.
> * **Máximo 4 posiciones abiertas simultáneas** (`MAX_CONCURRENT_POSITIONS=4`).
> * **Máximo 3 opciones por evento** (`MAX_ARB_OUTCOMES=3`) para eliminar el riesgo de sobre-exposición en canastas gigantes de 30 opciones.
> * **100% Arbitraje Puro de Cobertura Garantizada:** Sin trading especulativo, sin scalping direccional.

---

## 🛡️ Estrategias de Arbitraje (Workers en Paralelo)

> [!NOTE]
> **ESTADO ACTUAL (Agosto 2026):** El sistema corre en **modo MONITOREO** en Railway. Todos los workers están en `observation_only` (`ALLOWED_REAL_WORKERS=` vacío): registran oportunidades y alertan por Telegram, pero **no ejecutan órdenes ni gastan capital real**. La única fuente real de alertas hoy es el **Resolution Sniper (crypto)**; los arbitrajes deportivos no generan oportunidades porque los mercados están eficientemente valorados.

Workers definidos en `WORKER_PROFILE_MODE=pure_arbitrage` (solo los habilitados corren):

| Worker ID | Nombre del Worker | Plataforma / Feeder | Estado | Función |
| :--- | :--- | :--- | :--- | :--- |
| **Worker 1** | Limitless Intraday General | `limitless_ws` | ⏸️ `WORKER1_ENABLED=false` | Arbitraje Same-Day crypto ($1 \times N$ <24h). |
| **Worker 2** | Cross-Platform Sports | `multi_platform` | ✅ ON | Arbitraje Deportivo Limitless vs Kalshi/Polymarket. **Sin overlap de mercados → 0 oportunidades.** |
| **Worker 3** | Sports 3 Opciones | `limitless_sports` | ✅ ON | Arbitraje $1 \times N$ en canastas de 3+ outcomes (intra-platform). |
| **Worker 4** | Sports 2 Opciones | `limitless_sports` | ✅ ON | Arbitraje $1 \times N$ en binarios YES/NO, O/U (intra-platform). |
| **Worker 5** | Binance HFT Oracle | `binance` | ✅ ON (sin datos) | Oráculo Spot BTCUSDT. **Geo-bloqueado (HTTP 451) → sin feed.** |
| **Worker 6** | Crypto Atomic-Arb | `limitless_ws` | ⏸️ `WORKER6_ENABLED=false` | Arbitraje de opciones Bitcoin intraday. |
| **Worker 7** | Resolution Sniper | `resolution_sniper` | ✅ ON | Compra YES a 0.95-0.98 en mercados casi resueltos. **Fuente principal de alertas.** |

---

## 🧮 Ejemplo de Arbitraje $1 \times N$ Ejecutado en Vivo

En un partido de la UEFA Champions League (*Lincoln Red Imps FC vs Mjallby AIF*), con 3 resultados exclusivos:

1. **Gana Lincoln Red Imps:** Comprado a **$0.1640 USD**
2. **Gana Mjallby AIF:** Comprado a **$0.6235 USD**
3. **Empate:** Comprado a **$0.1740 USD**

$$\text{Costo Total} = \$0.1640 + \$0.6235 + \$0.1740 = \mathbf{\$0.9615\text{ USD}}$$
$$\text{Cobro Garantizado al Finalizar} = \mathbf{\$1.0000\text{ USD}}$$
$$\text{Ganancia Neta Asegurada} = \mathbf{+\$0.0385\text{ USD (+3.85\% ROI neto)}}$$

---

## 📐 Arquitectura del Sistema

```text
┌─────────────────────────────────────────────────────────────────┐
│                         FRONTEND (web/)                          │
│              Dashboard HTML/JS — Puerto 8080                    │
└────────────────────────────┬────────────────────────────────────┘
                             │ HTTP REST / WebSockets
┌────────────────────────────▼────────────────────────────────────┐
│                    FastAPI API (backend/src/api/app.py)         │
│     /api/status   /api/trades   /api/arbitrage   /api/workers   │
└───────────┬────────────────────────────────────────────┬────────┘
            │                                            │
┌───────────▼──────────────┐              ┌─────────────▼────────┐
│    TradingEngine          │              │   DatabaseManager     │
│  (src/engine/supervisor) │◄────────────►│ (src/database/conn)  │
│                           │              │   PostgreSQL 16      │
│  ┌──────────────────────┐ │              └──────────────────────┘
│  │   asyncio.Queue       │ │
│  │                       │ │
│  │  PriceUpdateEvent ──► │ │
│  │  SignalEvent      ──► │ │
│  │  OrderEvent       ──► │ │
│  └──────────────────────┘ │
│            │               │
│  ┌─────────▼────────────┐  │
│  │      Feeders         │  │
│  │ (Limitless/Kalshi/   │  │
│  │  Alpaca/Binance)     │  │
│  └──────────────────────┘  │
└──────────────────────────────┘
```

---

## 📦 Estructura del Repositorio

```text
auto_trade/
├── main.py                  # Entrypoint principal (Uvicorn puerto 8080)
├── Dockerfile               # Imagen Docker de producción (python:3.10-slim + uv)
├── docker-compose.yml       # Orquestador (trading_bot_backend + trading_bot_db)
├── pyproject.toml           # Dependencias administradas por Astral uv
├── .env                     # Variables de entorno activas (gitignored)
├── .env.template            # Plantilla de configuración
│
├── backend/                 # Código fuente principal de Python
│   └── src/
│       ├── api/
│       │   └── app.py       # FastAPI REST endpoints + WebSockets
│       ├── database/
│       │   └── connection.py # Capa de datos PostgreSQL (psycopg2)
│       ├── engine/
│       │   ├── supervisor.py # Motor Multi-Worker (TradingEngine / TradingWorker)
│       │   └── friction_guard.py # Módulo Anti-Fricción y Comisiones
│       ├── feeders/
│       │   ├── base.py
│       │   ├── limitless_sports_feeder.py # Escaneo de mercados de fútbol
│       │   ├── kalshi_feeder.py          # WebSocket REST Auth RSA PSS Kalshi Demo
│       │   ├── alpaca_feeder.py          # Crypto Quotes Stream Alpaca
│       │   └── binance_feeder.py         # Oráculo de Referencia HFT Spot
│       └── strategy/
│           ├── sports_arb.py            # Arbitraje 1xN intra-plataforma
│           ├── cross_platform_arb.py    # Arbitraje cruzado de precios
│           └── cross_platform_tracker.py# Rastreador centralizado de cotizaciones
│
└── web/                     # Frontend estático servido en puerto 8080
    ├── index.html           # Dashboard principal (TradingView charts + Workers tabs)
    ├── style.css            # Estilos UI Dark Mode Neumórfico
    └── app.js               # Lógica JS (Streaming WebSocket + REST Polling)
```

---

## ⚙️ Stack Tecnológico

| Componente | Tecnología |
| :--- | :--- |
| **Backend** | Python 3.10+, FastAPI, Uvicorn, Asyncio |
| **Base de Datos** | PostgreSQL 16 (Append-only portfolio & trades) |
| **Gestión de Paquetes** | Astral `uv` |
| **Contenedores** | Docker / docker-compose |
| **Exchanges Integrados** | Limitless Exchange (Base L2), Kalshi Demo (RSA PSS), Alpaca Crypto, Binance Spot |
| **Frontend** | HTML5, Vanilla JS, CSS3, Lightweight-Charts |

---

## 🚀 Despliegue Rápido con Docker (Recomendado)

### 1. Iniciar los contenedores
```bash
docker-compose up -d --build
```

### 2. Abrir el Dashboard en el Navegador
Navegar a: **`http://localhost:8080`**

### 3. Verificar Estado de los Contenedores
```bash
docker ps
docker logs -f trading_bot_backend
```

---

## 🔧 Variables de Entorno Clave (`.env`)

| Variable | Descripción | Valor por Defecto |
| :--- | :--- | :---: |
| `MAX_CONCURRENT_POSITIONS` | Límite máximo de posiciones simultáneas activas | `4` |
| `MAX_ARB_OUTCOMES` | Límite máximo de opciones por canasta de arbitraje | `3` |
| `NEGRISK_MAX_OUTCOMES` | Límite de opciones para mercados NegRisk | `3` |
| `KALSHI_ENV` | Entorno de Kalshi (`demo` o `prod`) | `demo` |
| `KALSHI_API_KEY_ID` | Key ID para firma RSA en Kalshi | `cb0d6311...` |
| `KALSHI_PRIVATE_KEY_PATH` | Ruta a la clave privada RSA `.pem` | `C:\Users\User\Downloads\kalshi_private_key.pem` |
| `SPORTS_POLL_INTERVAL` | Frecuencia de escaneo en segundos para Limitless Sports | `1.0` |
| `AUTO_START` | Auto-inicio de workers al levantar el contenedor | `true` |
| `LIMITLESS_USE_WEBSOCKET` | Usar WebSocket para crypto workers (evita polling) | `true` |

---

## 📋 Documentación de Plataformas de Trading (Referencia API)

### Limitless Exchange (Base L2 CLOB)

| Campo | Descripción |
| :--- | :--- |
| **Modelo** | Binary contracts (YES/NO). Settlement: $1.00 (win) / $0.00 (lose). |
| **Price** | 0.00 – 1.00 USD por share. |
| **Order type** | CLOB limit orders, post-only preferred (0% fees). |
| **Sizing** | `amount` = number of shares to buy. `spend_usd = amount × price`. |
| **Settlement** | Automatic on event resolution. Winning side gets $1.00 × shares held. |
| **Key API** | `limitless_sdk.api.HttpClient` → REST. On-chain settlement on Base L2. |
| **Fee model** | Maker 0% (post-only), Taker varies. We use post-only exclusively. |
| **Risk** | Pure arbitrage: buy all N outcomes at total cost < $1.00, guaranteed $1.00 payout. |

### Kalshi (Event Contracts)

| Campo | Descripción |
| :--- | :--- |
| **Modelo** | Binary event contracts. Settlement: $1.00 (yes) / $0.00 (no). |
| **Price** | `yes_price` in cents (1–99). Equivalent to $0.01–$0.99. |
| **Order type** | REST API with RSA-PSS signature authentication. |
| **Sizing** | `count` = number of contracts. `spend_usd = count × price_in_dollars`. |
| **Settlement** | Automatic on event expiry. YES holders get $1.00 × count. |
| **Auth** | `KALSHI-ACCESS-KEY` + RSA-PSS signed `timestamp + method + path`. |
| **Fee model** | No commission on demo. Production fees vary by market. |
| **Endpoints** | `POST /portfolio/orders` (create), `GET /portfolio/positions` (sync). |

### Polymarket (CLOB Prediction Markets)

| Campo | Descripción |
| :--- | :--- |
| **Modelo** | Binary/multi-outcome event tokens. Settlement: $1.00 or $0.00 per token. |
| **Price** | 0.00 – 1.00 USDC per share. |
| **Order type** | CLOB limit orders via REST API (Polygon blockchain settlement). |
| **Sizing** | `size` = USDC amount to spend. `amount_of_shares = size / price`. |
| **Settlement** | Smart contract resolution on Polygon. USDC payout to token holders. |
| **Fee model** | Maker rebates available, Taker fee varies. |
| **Note** | Cross-platform arb vs Limitless: same binary model enables direct price comparison. |

### Alpaca (Crypto/Stock Broker)

| Campo | Descripción |
| :--- | :--- |
| **Modelo** | Traditional spot/fractional shares. |
| **Order type** | Market orders via Python SDK (`alpaca-py`). |
| **Sizing** | `qty` = number of shares/units. Fractional for crypto. |
| **Settlement** | T+0 for crypto, T+1 for stocks. |
| **Auth** | API key + secret (header-based). |
| **Fee model** | $0 commission for crypto. |

### Binance (Spot Oracle)

| Campo | Descripción |
| :--- | :--- |
| **Modelo** | Spot reference price (not executed). Used as price oracle/lead-lag reference. |
| **Feed** | WebSocket `@bookTicker` stream (real-time bid/ask). |
| **Purpose** | Provides "true" market price for Lead-Lag arbitrage detection. |
| **Note** | BinanceFeeder is NOT an execution venue — only a reference feed. |

---

## 📡 Notificaciones de Telegram (Activas)

El bot envía alertas por Telegram (token de `TELEGRAM_BOT_TOKEN`):

| Tipo de Alerta | Cuándo se envía | Dedup / Límite |
| :--- | :--- | :--- |
| **Oportunidad de sniper** | El Resolution Sniper detecta YES ≥0.95 con liquidez | 1 por evento por hora |
| **Resultado de mercado** (`Mercado resuelto`) | Un mercado monitoreado resuelve (YES/NO) | 1 única vez por evento (`_sent_resolution_alerts`, TTL 30d) |

**Protecciones anti-spam implementadas (fix `70a3ac4`):**
- Dedup de resoluciones en memoria: un evento nunca se re-alerta (`has_resolution_alerted`).
- Rate limit global: `TELEGRAM_MIN_INTERVAL_SECONDS` (default 5s) — los envíos excesivos se **saltan** (no bloquean el loop).
- `record_opportunity` es un **upsert por `event_id`** (antes insertaba una fila nueva por cada scan → bloat en `edge_snapshots`).
- `update_opportunity_resolution` marca todas las filas cuyo `event_id` contenga el slug (cubre prefijos `limitless_sniper_/sport_/crypto_`).
- Ventana de stale: `OPPORTUNITY_STALE_HOURS` (default 6) para sacar de la cola pending mercados que no resuelven.

**Nota (HTTP 409):** Un segundo poller de `getUpdates` con el mismo token puede existir en algún lugar externo (VPS/otro PaaS). Solo afecta comandos entrantes (`/status`, `/workers`); las alertas salientes no se ven afectadas. Se resuelve revocando el token en @BotFather.

---

## 🛣️ Roadmap / Próximos Pasos (Futuros Cambios)

- [ ] **Despliegue local 24/7 en Nvidia Jetson Nano (4GB) / Raspberry Pi:** Migración del bot a un servidor local de bajo consumo de energía una vez que las estrategias hayan sido validadas empíricamente en el entorno de pruebas.
- [ ] **Habilitar ejecución real del Resolution Sniper:** emitir `SignalEvent` en `resolution_sniper.py` + agregar `worker_7` a `ALLOWED_REAL_WORKERS`. **Requiere dinero real.**
- [ ] **Optimización de lectura multihilo para feeders REST.**
- [ ] **Consolidar duplicados históricos** de `edge_snapshots` (fila por `event_id`) en producción.
- [ ] **Investigar el segundo poller Telegram (409):** revocar token en @BotFather.

---

## 📝 Reglas de Mantenimiento

* **Sin commits innecesarios:** Solo ejecutar `git commit` cuando el usuario lo solicite explícitamente.
* **Portfolio Append-Only:** La tabla `portfolio_state` no permite `UPDATE`. Solo realiza `INSERT` y lecturas con `DISTINCT ON (asset)`.
* **Worker Isolation:** Todos los métodos de base de datos están aislados y filtrados por `worker_id`.

---

*Actualizado: Agosto 2026 — auto_trade multi-worker Docker production deployment*
