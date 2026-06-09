# Guía de Desarrollo — auto_trade

> Referencia rápida para onboarding de nuevos desarrolladores y para retomar el proyecto en el futuro.

---

## Setup del Entorno de Desarrollo

### Prerequisitos
- Python 3.10+
- Docker Desktop
- `uv` (gestor de paquetes): `pip install uv`

### Pasos

```bash
# 1. Clonar repositorio
git clone <repo-url>
cd auto_trade

# 2. Instalar dependencias
uv sync

# 3. Configurar .env
cp .env.template .env
# Editar .env — para desarrollo local, los valores por defecto de la DB son suficientes

# 4. Levantar PostgreSQL
docker-compose up -d

# Verificar que la DB está lista:
docker-compose ps
# Debe aparecer: trading_bot_db ... healthy

# 5. Ejecutar el bot
uv run python main.py
# o simplemente:
python main.py  # (si el venv está activado)

# 6. Abrir el dashboard
# http://localhost:8080
```

---

## Modos de Operación

### Modo Mock (Desarrollo/Testing)
```env
FEEDER_TYPE=mock
TRADING_SYMBOL=BTCUSDT
```
- No requiere credenciales de broker
- Genera precios sinusoidales automáticamente
- Las señales EMA+RSI se disparan en unos minutos

### Modo OANDA (Forex Real — Demo)
```env
FEEDER_TYPE=oanda
TRADING_SYMBOL=EUR_USD
OANDA_ACCOUNT_ID=...
OANDA_API_TOKEN=...
OANDA_ENV=practice
```
- Requiere cuenta en [oanda.com](https://www.oanda.com) (gratis para demo)
- Precios de mercado reales en streaming

### Modo IG Group (Demo)
```env
FEEDER_TYPE=ig
TRADING_SYMBOL=CS.D.EURUSD.TODAY.IP
IG_USERNAME=...
IG_PASSWORD=...
IG_API_KEY=...
IG_ACC_NUMBER=...
IG_ENV=DEMO
```
- Requiere cuenta en [ig.com](https://www.ig.com)
- Los símbolos `EURUSD` y `GBPUSD` se convierten automáticamente al epic IG

---

## Extender el Sistema

### Agregar una Nueva Estrategia

1. Crear `src/strategy/mi_estrategia.py`:

```python
from src.strategy.base import BaseStrategy
from src.events import PriceUpdateEvent, SignalEvent

class MiEstrategia(BaseStrategy):
    def __init__(self, symbol: str):
        super().__init__(symbol)
        # Tu inicialización aquí

    def evaluate_signal(self, event: PriceUpdateEvent) -> SignalEvent | None:
        # Necesitas al menos N precios para calcular indicadores
        if len(self.prices_df) < 10:
            return None

        # Tu lógica de señal aquí
        # self.prices_df tiene columnas: timestamp, price
        
        # Retornar señal o None
        return SignalEvent(self.symbol, "BUY", event.price, "Mi razón")
```

2. Instanciarla en `src/engine.py`:

```python
from src.strategy.mi_estrategia import MiEstrategia

# En TradingEngine.__init__():
self.strategy = MiEstrategia(self.symbol)
```

### Agregar un Nuevo Feeder (Broker)

1. Crear `src/feeders/mi_feeder.py`:

```python
import asyncio
from src.feeders.base import BaseFeeder
from src.events import PriceUpdateEvent

class MiFeeder(BaseFeeder):
    def __init__(self, symbol: str, event_queue: asyncio.Queue):
        super().__init__(symbol, event_queue)

    async def start(self):
        self.running = True
        while self.running:
            # Obtener precio de tu fuente
            price = await obtener_precio()
            event = PriceUpdateEvent(self.symbol, price)
            await self.queue.put(event)
```

2. Agregar la condición en `src/engine.py`:

```python
elif self.feeder_type == "mi_feeder":
    self.feeder = MiFeeder(self.symbol, self.queue)
```

3. Agregar variables en `.env.template`.

### Agregar un Nuevo Endpoint API

En `src/api.py`:

```python
@app.get("/api/mi_endpoint")
async def mi_endpoint():
    """Descripción para la documentación automática de FastAPI."""
    # FastAPI genera /docs con Swagger automáticamente
    return {"dato": "valor"}
```

---

## Inspección de la Base de Datos

```bash
# Conectar a PostgreSQL en Docker
docker exec -it trading_bot_db psql -U trading_user -d trading_bot

# Consultas útiles:
SELECT * FROM trades ORDER BY timestamp DESC LIMIT 10;
SELECT * FROM logs ORDER BY timestamp DESC LIMIT 20;
SELECT DISTINCT ON (asset) asset, free_balance FROM portfolio_state ORDER BY asset, timestamp DESC;
SELECT * FROM bot_state;

# Limpiar datos de prueba:
TRUNCATE trades, logs, portfolio_state;
DELETE FROM bot_state WHERE key = 'bot_running';
```

---

## Documentación Automática de la API

FastAPI genera documentación interactiva automáticamente:
- **Swagger UI**: http://localhost:8080/docs
- **ReDoc**: http://localhost:8080/redoc

---

## Troubleshooting Común

### La DB no conecta al arrancar
```
[Error de DB] No se pudo inicializar la base de datos: ...
```
**Solución**: Asegurarse de que Docker esté corriendo y el contenedor esté healthy:
```bash
docker-compose up -d
docker-compose ps  # debe decir "healthy"
```

### El feeder IG no conecta
```
[Feeder IG] ERROR: IG_USERNAME, IG_PASSWORD o IG_API_KEY faltan
```
**Solución**: Verificar que el archivo `.env` tenga las credenciales IG correctas y que `FEEDER_TYPE=ig`.

### Las señales EMA+RSI tardan en aparecer
**Normal**: La estrategia necesita `max(ema_long, rsi_period) + 2 = 23` ticks mínimos antes de generar señales. Con el MockFeeder a 1 tick/segundo, tarda ~23 segundos.

### `trading_bot.db` en el directorio raíz
Este es un archivo SQLite residual — el proyecto **usa PostgreSQL**. El archivo SQLite puede ignorarse o eliminarse.

---

## Variables de Estado del Bot (`bot_state`)

| Key            | Valores posibles        | Descripción                   |
|----------------|-------------------------|-------------------------------|
| `bot_running`  | `"true"`, `"false"`     | Si el engine está activo       |
| `trading_mode` | `"paper"`, `"live"`     | Modo de operación              |

---

*Actualizado: junio 2026*
