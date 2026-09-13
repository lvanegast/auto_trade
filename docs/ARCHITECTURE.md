# Decisiones de Arquitectura — auto_trade

> Este documento captura el **"por qué"** detrás de las decisiones técnicas del proyecto.
> Es una guía para futuros proyectos similares.

---

## ADR-001: Arquitectura Event-Driven con `asyncio.Queue`

**Estado**: ✅ Adoptado

**Contexto**: Un bot de trading necesita procesar datos de precio en tiempo real, evaluarlos con una estrategia, y ejecutar órdenes. Todo esto de forma asíncrona y sin bloqueos.

**Decisión**: Se implementó un bus de eventos basado en `asyncio.Queue`. Los feeders producen eventos (`PriceUpdateEvent`), el engine los consume, y la estrategia puede generar nuevos eventos (`SignalEvent`) que vuelven a la cola.

**Consecuencias**:
- ✅ Desacoplamiento total entre productores y consumidores
- ✅ Fácil agregar nuevos tipos de eventos sin modificar el núcleo
- ✅ Compatible con `asyncio` nativo de Python — sin dependencias extra
- ⚠️ La cola es in-memory: si el proceso muere, los eventos pendientes se pierden

**Alternativas consideradas**: Redis Streams (overkill para una app single-process), callbacks directos (acoplamiento fuerte).

---

## ADR-002: PostgreSQL como única fuente de verdad

**Estado**: ✅ Adoptado

**Contexto**: El bot necesita persistir trades, logs y estado del portafolio de forma confiable. El estado debe sobrevivir reinicios.

**Decisión**: Se usa PostgreSQL 16 para todas las tablas. Docker Compose levanta la DB en un contenedor aislado. El esquema se crea automáticamente con `CREATE TABLE IF NOT EXISTS` al iniciar.

**Consecuencias**:
- ✅ Datos persistentes entre reinicios del bot
- ✅ Consultas SQL complejas posibles (ej: `DISTINCT ON` para estado de portafolio)
- ✅ Fácil inspección manual con cualquier cliente SQL
- ⚠️ Requiere Docker instalado para el desarrollo local
- ⚠️ `psycopg2` crea una nueva conexión por operación (sin pool) — acceptable para volúmenes bajos

**Nota importante**: `portfolio_state` es una tabla de **eventos inmutables** (append-only). El estado actual se obtiene con:
```sql
SELECT DISTINCT ON (asset) asset, free_balance, locked_balance
FROM portfolio_state
ORDER BY asset, timestamp DESC;
```
Esto evita UPDATE/DELETE y mantiene historial completo.

---

## ADR-003: Strategy Pattern para estrategias de trading

**Estado**: ✅ Adoptado

**Contexto**: Las estrategias de trading varían enormemente. Se necesita un sistema extensible que permita agregar nuevas estrategias sin tocar el motor.

**Decisión**: `BaseStrategy` define el contrato con un método abstracto `evaluate_signal()`. El Template Method `on_price_update()` acumula precios y llama a `evaluate_signal()`. Las subclases solo implementan la lógica de señal.

**Para agregar una nueva estrategia**:
```python
# src/strategy/mi_estrategia.py
from src.strategy.base import BaseStrategy

class MiEstrategia(BaseStrategy):
    def evaluate_signal(self, event):
        # Tu lógica aquí
        return SignalEvent(...) or None
```
Luego instanciarla en `engine.py`.

---

## ADR-004: Feeders intercambiables via variable de entorno

**Estado**: ✅ Adoptado

**Contexto**: El mismo bot debe funcionar en modo simulado (sin internet), con OANDA (Forex) o con IG Group, solo cambiando configuración.

**Decisión**: `FEEDER_TYPE` en `.env` controla qué implementación de `BaseFeeder` se instancia en `TradingEngine.__init__()`. Las credenciales de cada broker están en variables de entorno separadas.

**Consecuencias**:
- ✅ Cambiar de broker no requiere modificar código
- ✅ El modo `mock` permite desarrollo completamente offline
- ✅ `.env.template` documenta todas las variables necesarias

---

## ADR-005: FastAPI sirve también el frontend estático

**Estado**: ✅ Adoptado

**Contexto**: El dashboard web necesita ser accesible sin un servidor web separado (nginx, etc.) en desarrollo.

**Decisión**: FastAPI monta la carpeta `web/` como archivos estáticos en la raíz `/`. Esto simplifica el deploy a un único proceso en un único puerto (8080).

```python
app.mount("/", StaticFiles(directory="web", html=True), name="web")
```

**Consecuencias**:
- ✅ Un solo proceso, un solo puerto — deploy simple
- ✅ Sin necesidad de CORS en producción si el frontend está en el mismo origen
- ⚠️ El `StaticFiles` mount DEBE ir al final — las rutas `/api/*` se registran antes

---

## ADR-006: Paper Trading por defecto — never live sin intención explícita

**Estado**: ✅ Adoptado

**Contexto**: El riesgo de ejecutar trades reales accidentalmente es altísimo.

**Decisión**: El bot arranca siempre en estado OFFLINE (`bot_running = false`). El usuario debe presionar "Iniciar" en el dashboard. Actualmente **solo paper trading** está implementado — live trading requiere desarrollo adicional.

**Mecanismo de seguridad**:
- Estado inicial: `db.set_state("bot_running", "false")` en `startup_event()`
- El balance virtual se inicializa con 10,000 unidades del activo cotizado
- Las operaciones reales no se ejecutan — solo se simulan y registran en DB

---

## ADR-007: Gestión de dependencias con `uv`

**Estado**: ✅ Adoptado

**Contexto**: `pip` + `venv` es lento. Se buscó una alternativa moderna.

**Decisión**: Se usa [`uv`](https://github.com/astral-sh/uv) como gestor de paquetes. El proyecto tiene `pyproject.toml` como fuente de verdad y `uv.lock` para reproducibilidad exacta.

**Comandos clave**:
```bash
uv sync          # Instalar dependencias del lockfile
uv add <pkg>     # Agregar dependencia
uv run python main.py  # Ejecutar en el entorno virtual
```

---

## Lecciones Aprendidas

### IG Feeder y Lightstreamer
- IG Group usa **Lightstreamer** (protocolo propietario sobre WebSocket) para streaming de precios
- Los campos de precio son `BID` y `OFFER` (no `ASK`)
- Los "epics" IG tienen formato largo: `CS.D.EURUSD.TODAY.IP`
- El streaming corre en un **hilo separado** (`asyncio.to_thread`) — para insertar en la `asyncio.Queue` desde un thread externo se usa `asyncio.run_coroutine_threadsafe()`

### Estrategia EMA+RSI — Ajuste de parámetros RSI
- Los rangos de RSI para señales se ajustaron para capturar mejor las oscilaciones del MockFeeder:
  - BUY: RSI entre 40 y 85 (en lugar del clásico <30)
  - SELL: RSI entre 15 y 60 (en lugar del clásico >70)
- Esto refleja que el MockFeeder genera oscilaciones más amplias que el mercado real

### `DISTINCT ON` en PostgreSQL para estado actual
- La tabla `portfolio_state` es append-only para mantener historial
- `DISTINCT ON (asset) ... ORDER BY asset, timestamp DESC` es la forma eficiente de obtener el balance más reciente por activo en PostgreSQL

---

## ADR-008: Normalización Semántica Cross-Exchange (`SportsMatcher`)

**Estado**: ✅ Adoptado

**Contexto**: Polymarket US, Limitless y Kalshi listan los mismos partidos reales pero con variaciones de títulos ("Man City vs Arsenal" vs "Arsenal vs Manchester City"), sufijos de regulación ("(Reg. Time)") y notaciones norteamericanas ("GB @ PIT"). Si los slugs no coinciden exactamente, el arbitraje cross-platform falla silenciosamente.

**Decisión**: Se implementó `SportsMatcher` (`backend/src/utils/sports_matcher.py`) con:
- Diccionario de más de 120 entidades deportivas (Fútbol, Tenis, Esports, NFL, NBA).
- Ordenamiento alfabético determinista de los contrincantes (`team_a < team_b`) para que el slug sea invariante al orden local/visitante.
- Limpieza de sufijos y normalización de outcomes ("Draw", "Tie", "Tie (Reg. Time)" -> "draw").

**Consecuencias**:
- ✅ 100% de consistencia de `event_id` entre exchanges para eventos idénticos.
- ✅ Elimina falsos negativos en `cross_platform_tracker`.

---

## ADR-009: Cobertura Combinatoria con Dual Simplex en Python Puro

**Estado**: ✅ Adoptado

**Contexto**: Mercados correlacionados en un partido (Moneyline 3-way + Over/Under 2.5 + BTTS) presentan ineficiencias de precios. Se necesita calcular la canasta óptima de cobertura $\min c^T x$ sujeto a $A x \ge \mathbf{1}, x \ge 0$ sin dependencias externas como SciPy o solvers en C que compliquen la arquitectura ARM64 en Jetson Nano.

**Decisión**: Se implementó `CoveringLPSolver` (`backend/src/strategy/combinatorial_arb.py`) usando el método Dual Simplex en Python puro (listas de floats). En el modelo de fútbol se particiona el espacio de resultados en **9 estados atómicos mutuamente excluyentes y colectivamente exhaustivos**.

**Consecuencias**:
- ✅ Resuelve la canasta en ~2ms en CPU ARM64 con cero dependencias externas.
- ✅ Si $c^* < 1.00$, garantiza payout de $\$1.0000$ en cualquier resultado del partido (arbitraje 100% puro).

---

*Actualizado: septiembre 2026 — auto_trade v0.3.0*
