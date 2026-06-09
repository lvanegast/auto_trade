# 🤖 Auto Trade — Bot de Trading Event-Driven

> Bot de trading algorítmico con arquitectura event-driven, dashboard web en tiempo real y soporte para brokers reales (IG Group, OANDA) y modo simulado (paper trading).

---

## 📐 Arquitectura General

El sistema sigue un patrón **event-driven** basado en una cola asíncrona (`asyncio.Queue`). Los componentes producen y consumen eventos de forma desacoplada:

```
┌─────────────────────────────────────────────────────────────────┐
│                         FRONTEND (web/)                          │
│              Dashboard HTML/JS — Puerto 8080                    │
└────────────────────────────┬────────────────────────────────────┘
                             │ HTTP / REST
┌────────────────────────────▼────────────────────────────────────┐
│                     FastAPI API (src/api.py)                     │
│        /api/status  /api/trades  /api/logs  /api/start /stop    │
└───────────┬────────────────────────────────────────────┬────────┘
            │                                            │
┌───────────▼──────────────┐              ┌─────────────▼────────┐
│    TradingEngine          │              │   DatabaseManager     │
│    (src/engine.py)        │◄────────────►│   (src/database.py)  │
│                           │              │   PostgreSQL          │
│  ┌──────────────────────┐ │              └──────────────────────┘
│  │   asyncio.Queue       │ │
│  │                       │ │
│  │  PriceUpdateEvent ──► │ │
│  │  SignalEvent      ──► │ │
│  │  OrderEvent       ──► │ │
│  └──────────────────────┘ │
│            │               │
│  ┌─────────▼────────────┐  │
│  │      Feeder           │  │
│  │  (Mock/OANDA/IG)      │  │
│  └──────────────────────┘  │
│  ┌─────────────────────┐   │
│  │     Strategy         │   │
│  │   (EMA + RSI)        │   │
│  └─────────────────────┘   │
└──────────────────────────────┘
```

### Flujo de un Tick de Precio

```
Feeder → PriceUpdateEvent → Queue → Engine → Strategy.on_price_update()
                                                    │
                                         (Si hay cruce EMA + RSI válido)
                                                    │
                                              SignalEvent → Queue → Engine._execute_order()
                                                                          │
                                                                    Actualiza DB (trade + portfolio)
```

---

## 📦 Estructura del Proyecto

```
auto_trade/
├── main.py                  # Punto de entrada — levanta uvicorn en puerto 8080
├── pyproject.toml           # Metadatos del proyecto y dependencias (uv/pip)
├── requirements.txt         # Dependencias instalables por pip
├── docker-compose.yml       # Levanta PostgreSQL 16 en Docker
├── .env                     # Variables de entorno activas (NO subir a git)
├── .env.template            # Plantilla de configuración para nuevos devs
├── .gitignore
│
├── src/                     # Código fuente principal del backend
│   ├── __init__.py
│   ├── api.py               # Rutas FastAPI + CORS + mount del frontend
│   ├── engine.py            # Motor event-driven (TradingEngine)
│   ├── database.py          # Capa de acceso a datos PostgreSQL (DatabaseManager)
│   ├── events.py            # Clases de eventos: PriceUpdate, Signal, Order
│   │
│   ├── feeders/             # Fuentes de datos de mercado
│   │   ├── __init__.py
│   │   ├── base.py          # Clase abstracta BaseFeeder
│   │   ├── mock_feeder.py   # Simulador de precios sinusoidales (offline)
│   │   ├── oanda_feeder.py  # Streaming en tiempo real via OANDA v20 API
│   │   └── ig_feeder.py     # Streaming via IG Group + Lightstreamer
│   │
│   └── strategy/            # Estrategias de trading algorítmico
│       ├── __init__.py
│       ├── base.py          # Clase abstracta BaseStrategy (acumula precios en DataFrame)
│       └── ema_rsi.py       # Estrategia EMA 9/21 + RSI 14 con suavizado de Wilder
│
└── web/                     # Frontend estático (servido por FastAPI)
    ├── index.html           # Dashboard principal
    ├── style.css            # Estilos del dashboard
    └── app.js               # Lógica JS — polling al API, actualización de UI
```

---

## ⚙️ Stack Tecnológico

| Componente       | Tecnología                            |
|------------------|---------------------------------------|
| Backend          | Python 3.10+, FastAPI, Uvicorn        |
| Base de Datos    | PostgreSQL 16 (via Docker)            |
| ORM / Driver     | psycopg2-binary                       |
| Análisis         | pandas (DataFrames para indicadores)  |
| Broker Real 1    | OANDA v20 REST API (Forex)            |
| Broker Real 2    | IG Group + Lightstreamer (streaming)  |
| Frontend         | HTML5 + Vanilla JS + CSS              |
| Empaquetado      | uv (pyproject.toml), pip              |
| Contenedores     | Docker / docker-compose               |

---

## 🚀 Inicio Rápido

### 1. Clonar y configurar entorno

```bash
# Crear entorno virtual e instalar dependencias con uv
uv sync

# O con pip clásico
pip install -r requirements.txt
```

### 2. Configurar variables de entorno

```bash
cp .env.template .env
# Editar .env con tus credenciales
```

### 3. Levantar PostgreSQL con Docker

```bash
docker-compose up -d
```

### 4. Ejecutar el bot

```bash
python main.py
# Dashboard disponible en: http://localhost:8080
```

---

## 🔧 Configuración (`.env`)

| Variable           | Descripción                                            | Default         |
|--------------------|--------------------------------------------------------|-----------------|
| `DB_HOST`          | Host de PostgreSQL                                     | `localhost`     |
| `DB_PORT`          | Puerto de PostgreSQL                                   | `5432`          |
| `DB_NAME`          | Nombre de la base de datos                             | `trading_bot`   |
| `DB_USER`          | Usuario de PostgreSQL                                  | `trading_user`  |
| `DB_PASSWORD`      | Contraseña de PostgreSQL                               | `trading_password` |
| `FEEDER_TYPE`      | Fuente de datos: `mock`, `oanda`, `ig`                 | `mock`          |
| `TRADING_SYMBOL`   | Par de trading: `BTCUSDT`, `EUR_USD`, `GBP_USD`, epics de IG | `BTCUSDT`  |
| `TRADING_MODE`     | Modo de operación: `paper` (simulado)                  | `paper`         |
| `OANDA_ACCOUNT_ID` | ID de cuenta OANDA (solo si `FEEDER_TYPE=oanda`)       | —               |
| `OANDA_API_TOKEN`  | Token API de OANDA                                     | —               |
| `IG_USERNAME`      | Usuario de IG Group                                    | —               |
| `IG_PASSWORD`      | Contraseña de IG Group                                 | —               |
| `IG_API_KEY`       | API Key de IG (demo o live)                            | —               |
| `IG_ACC_NUMBER`    | Número de cuenta IG                                    | —               |
| `IG_ENV`           | Entorno IG: `DEMO` o `LIVE`                            | `DEMO`          |

---

## 📊 Estrategia: EMA + RSI

La estrategia implementada en `src/strategy/ema_rsi.py` combina dos indicadores clásicos:

### Indicadores
- **EMA 9** (corta): Media móvil exponencial de corto plazo
- **EMA 21** (larga): Media móvil exponencial de largo plazo
- **RSI 14**: Índice de Fuerza Relativa — suavizado con el método de Wilder (EWM con alpha = 1/14)

### Señales

| Señal | Condición                                                         |
|-------|-------------------------------------------------------------------|
| BUY   | EMA9 cruza hacia **arriba** a EMA21 **Y** RSI entre 40 y 85      |
| SELL  | EMA9 cruza hacia **abajo** a EMA21 **Y** RSI entre 15 y 60       |

> Las señales solo se emiten cuando **cambia el estado de posición**, evitando señales repetidas en la misma dirección.

### Ejecución (Paper Trading)
- **BUY**: Se gasta el 50% del saldo disponible en el activo cotizado (ej: USD)
- **SELL**: Se vende el 100% de la tenencia del activo base (ej: EUR, BTC)
- Mínimo de compra: 10 USD/USDT (o 1 unidad para otras divisas)

---

## 🌐 API REST

| Método | Endpoint       | Descripción                              |
|--------|----------------|------------------------------------------|
| GET    | `/api/status`  | Estado del bot, precio actual, portafolio |
| GET    | `/api/trades`  | Historial de operaciones (`?limit=N`)    |
| GET    | `/api/logs`    | Logs de auditoría (`?limit=N`)           |
| POST   | `/api/start`   | Inicia el bot de trading                 |
| POST   | `/api/stop`    | Detiene el bot de trading                |

---

## 🗄️ Esquema de Base de Datos

### `bot_state`
| Columna      | Tipo         | Descripción                        |
|--------------|--------------|------------------------------------|
| `key`        | VARCHAR(100) | Clave única de estado              |
| `value`      | TEXT         | Valor de la variable               |
| `updated_at` | TIMESTAMP    | Última actualización               |

### `trades`
| Columna             | Tipo          | Descripción                       |
|---------------------|---------------|-----------------------------------|
| `id`                | SERIAL PK     | ID autoincremental                |
| `timestamp`         | TIMESTAMP     | Momento de la operación           |
| `symbol`            | VARCHAR(20)   | Par de trading (ej: BTCUSDT)      |
| `side`              | VARCHAR(10)   | `BUY` o `SELL`                    |
| `price`             | NUMERIC(18,8) | Precio de ejecución               |
| `amount`            | NUMERIC(18,8) | Cantidad del activo base           |
| `total`             | NUMERIC(18,8) | Valor total (price × amount)      |
| `status`            | VARCHAR(20)   | `PENDING`, `COMPLETED`, `FAILED`  |
| `external_order_id` | VARCHAR(100)  | ID externo del broker (si aplica) |

### `logs`
| Columna     | Tipo        | Descripción                         |
|-------------|-------------|-------------------------------------|
| `id`        | SERIAL PK   | ID autoincremental                  |
| `timestamp` | TIMESTAMP   | Momento del log                     |
| `level`     | VARCHAR(10) | `INFO`, `WARNING`, `ERROR`          |
| `message`   | TEXT        | Mensaje del log                     |

### `portfolio_state`
| Columna          | Tipo          | Descripción                         |
|------------------|---------------|-------------------------------------|
| `id`             | SERIAL PK     | ID autoincremental                  |
| `timestamp`      | TIMESTAMP     | Momento del registro                |
| `asset`          | VARCHAR(20)   | Activo (ej: USD, EUR, BTC)          |
| `free_balance`   | NUMERIC(18,8) | Saldo disponible                    |
| `locked_balance` | NUMERIC(18,8) | Saldo bloqueado en órdenes          |

> El portafolio se inicializa con **10,000 unidades** del activo cotizado para paper trading.

---

## 🔌 Feeders (Fuentes de Datos)

### MockFeeder
- Genera precios **simulados sinusoidales** para pruebas sin conexión a internet
- Configurable: `interval` en segundos entre ticks
- Ideal para: testing de estrategias, demos, desarrollo offline

### OandaFeeder
- Conecta a la **OANDA v20 REST API** en modo streaming
- Soporta pares Forex: `EUR_USD`, `GBP_USD`, etc.
- Requiere cuenta demo o live en [oanda.com](https://www.oanda.com)

### IGFeeder
- Conecta a **IG Group** mediante **Lightstreamer** (WebSocket)
- Soporta epics IG: `CS.D.EURUSD.TODAY.IP`, `CS.D.GBPUSD.TODAY.IP`
- Convierte automáticamente símbolos simplificados (`EURUSD` → epic IG)
- Requiere cuenta en [ig.com](https://www.ig.com)

---

## 🧩 Patrones de Diseño Clave

### 1. Event-Driven Architecture
La cola `asyncio.Queue` desacopla productores (feeders) de consumidores (engine/strategy). Facilita agregar nuevos tipos de eventos sin modificar el núcleo.

### 2. Strategy Pattern
`BaseStrategy` define el contrato. `EmaRsiStrategy` implementa la lógica. Se pueden agregar nuevas estrategias implementando `evaluate_signal()`.

### 3. Template Method
`BaseStrategy.on_price_update()` acumula precios y llama a `evaluate_signal()` — subclases solo deben implementar la lógica de señal.

### 4. Repository Pattern
`DatabaseManager` encapsula toda la lógica de acceso a PostgreSQL. El engine y la API no conocen SQL directamente.

---

## 🔒 Seguridad

- El archivo `.env` está en `.gitignore` — **nunca subir credenciales al repositorio**
- CORS abierto (`*`) — para producción, restringir a dominios específicos
- Por defecto arranca en modo **OFFLINE** (el usuario activa desde la UI)

---

## 🛣️ Roadmap / Próximos Pasos

- [ ] Soporte para múltiples estrategias simultáneas (multi-strategy)
- [ ] Backtesting con datos históricos
- [ ] Sistema de notificaciones (email/Telegram) al ejecutar trades
- [ ] Gestión de riesgo avanzada (stop-loss, take-profit)
- [ ] Live trading (actualmente solo paper trading)
- [ ] Tests unitarios con `pytest`
- [ ] Autenticación en la API (JWT)
- [ ] Dockerizar el backend completo (no solo la DB)

---

## 📝 Notas de Desarrollo

- El bot arranca **apagado por defecto** (`bot_running = false`). Se activa desde el dashboard.
- El historial de precios en memoria se limita a **1000 ticks** para evitar consumo excesivo de RAM.
- `portfolio_state` es una tabla de **eventos inmutables** (append-only); el estado actual se obtiene con `DISTINCT ON`.
- Los logs se persisten tanto en consola como en PostgreSQL para trazabilidad completa.

---

*Generado automáticamente con el agente de documentación — actualizado: junio 2026*
