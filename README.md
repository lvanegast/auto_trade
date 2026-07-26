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

## 🛡️ Estrategias de Arbitraje Activas (7 Workers en Paralelo)

El sistema opera con 7 trabajadores (*workers*) independientes coordinados por `TradingEngine`:

| Worker ID | Nombre del Worker | Plataforma / Feeder | Tipo de Arbitraje / Función |
| :--- | :--- | :--- | :--- |
| **Worker 1** | Crypto BTC HFT | Limitless / Kalshi | Arbitraje Spot-to-Prediction (Lead-Lag vs Binance). |
| **Worker 2** | Cross-Platform Sports | Limitless vs Polymarket | Arbitraje Deportivo Cruzado 1xN (Mejores precios de canasta). |
| **Worker 3** | Limitless Sports (3 Opciones) | Limitless Exchange (Base L2) | Arbitraje Deportivo $1 \times N$ (Fútbol, Local/Visitante/Empate). |
| **Worker 4** | Limitless Sports (2 Opciones) | Limitless Exchange (Base L2) | Arbitraje Deportivo $1 \times N$ (Over/Under, Sí/No de 2 opciones). |
| **Worker 5** | Binance HFT Oracle | Binance Spot (`BTCUSDT`) | Oráculo Spot de Referencia a 0 latencia (Reloj Atómico del Sistema). |
| **Worker 6** | Maker Arbitrage MM | Limitless / Kalshi | Delta-Neutral Market Making (Post-Only, compra de YES + NO a < $0.95). |

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

---

## 🛣️ Roadmap / Próximos Pasos (Futuros Cambios)

- [ ] **Despliegue local 24/7 en Nvidia Jetson Nano (4GB) / Raspberry Pi:** Migración del bot a un servidor local de bajo consumo de energía una vez que las estrategias hayan sido validadas empíricamente en el entorno de pruebas.
- [ ] **Optimización de lectura multihilo para feeders REST.**
- [ ] **Configuración de notificaciones de Telegram para trades ejecutados.**

---

## 📝 Reglas de Mantenimiento

* **Sin commits innecesarios:** Solo ejecutar `git commit` cuando el usuario lo solicite explícitamente.
* **Portfolio Append-Only:** La tabla `portfolio_state` no permite `UPDATE`. Solo realiza `INSERT` y lecturas con `DISTINCT ON (asset)`.
* **Worker Isolation:** Todos los métodos de base de datos están aislados y filtrados por `worker_id`.

---

*Actualizado: Julio 2026 — auto_trade multi-worker Docker production deployment*
