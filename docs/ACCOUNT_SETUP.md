# Guia de Configuracion de Cuentas: Kalshi + Limitless

## Resumen Rapido

| Plataforma | Tipo | Registro | Deposito Minimo | API Auth |
|-----------|------|----------|----------------|----------|
| **Kalshi** | Prediction Markets (CFTC regulated) | kalshi.com + KYC | $20 USD (bank transfer) | RSA-PSS signature |
| **Limitless** | Prediction Markets (on-chain, Base L2) | Wallet connection | $10 USDC (on Base) | HMAC-SHA256 + EIP-712 |

---

## 1. Kalshi (Prediction Markets)

### Paso 1: Crear Cuenta
1. Ve a **https://kalshi.com** (produccion) o **https://demo.kalshi.co** (demo)
2. Click **Sign Up** - se requiere email y contraseña
3. Completa **KYC** (verificacion de identidad):
   - Nombre completo
   - Fecha de nacimiento
   - Numero de SSN (ultimos 4 digitos)
   - Direccion
   - Foto de ID gubernamental
4. Espera aprobacion (usualmente 1-2 dias habiles)

### Paso 2: Generar API Keys
1. Login en tu cuenta Kalshi
2. Ve a **Account Settings** → **API Keys**
3. Click **Create New API Key**
4. **Descarga el Private Key** (archivo `.key` o `.pem`) - **NO se puede recuperar despues**
5. **Copia el API Key ID** (UUID como `a952bcbe-ec3b-4b5b-b8f9-11dae589608c`)
6. Permisos recomendados:
   - ✅ Read (leer mercados, posiciones, balances)
   - ✅ Trade (colocar y cancelar ordenes)
   - ❌ Withdraw (NUNCA para un bot)

### Paso 3: Configurar en .env
```bash
# Credenciales Kalshi
KALSHI_API_KEY_ID=tu_api_key_id_de_kalshi
KALSHI_PRIVATE_KEY_PATH=/ruta/a/tu/kalshi_private_key.pem
# 'demo' para sandbox, 'prod' para dinero real
KALSHI_ENV=demo
```

### Paso 4: Verificar Conexion
```bash
# Test rapido con el SDK
pip install kalshi-python-sync

python -c "
from kalshi_python_sync import Configuration, KalshiClient
import os

config = Configuration(host='https://demo-api.kalshi.co/trade-api/v2')
config.api_key_id = os.getenv('KALSHI_API_KEY_ID')
with open(os.getenv('KALSHI_PRIVATE_KEY_PATH'), 'r') as f:
    config.private_key_pem = f.read()

client = KalshiClient(config)
balance = client.get_balance()
print(f'Balance: \${balance[\"balance\"]/100:.2f}')
"
```

### URLs de Kalshi
| Entorno | REST API | WebSocket |
|---------|----------|-----------|
| Demo | `https://demo-api.kalshi.co/trade-api/v2` | `wss://demo-api.kalshi.co/trade-api/ws/v2` |
| Produccion | `https://api.elections.kalshi.com/trade-api/v2` | `wss://api.elections.kalshi.com/trade-api/ws/v2` |

### Notas Importantes
- Kalshi cobra **~1.75% fee por contrato** (maximo, decrece en extremos de precio)
- **Maker orders** (limit) pagan **$0 fee** en la mayoria de mercados
- El fee es un "dome" que pica a 50¢: `⌈0.07 × price × (1-price) × 100⌉ centavos`
- Usa **limit orders** (maker) para evitar fees
- Timestamp debe estar en **milisegundos** (no segundos)
- Reloj sincronizado con NTP es critico (ventana de 1 segundo)

---

## 2. Limitless Exchange (Prediction Markets)

### Paso 1: Preparar Wallet
1. Instala **MetaMask** o **Rabby Wallet** (browser extension)
2. Crea una **wallet dedicada** para trading (NO uses tu wallet principal)
3. Exporta la private key - la necesitaras para el bot

### Paso 2: Fondos en Base Network
Limitless opera en **Base** (L2 de Ethereum). Necesitas:

| Activo | Uso | Cantidad Minima |
|--------|-----|----------------|
| **USDC** (en Base) | Para trades | $10-50 |
| **ETH** (en Base) | Gas fees | $1-2 |

**Como fondar:**
1. Ve a **https://bridge.base.org**
2. Deposita USDC y ETH desde tu wallet principal o exchange
3. Asegurate de que los tokens estan en la **red Base** (chainId: 8453)

### Paso 3: Crear API Token
1. Ve a **https://limitless.exchange**
2. Conecta tu wallet (MetaMask/Rabby)
3. Abre tu perfil → **API Tokens** tab
4. Click **Derive** → copia `tokenId` y `secret`
5. **El secret solo se muestra UNA VEZ** - guardalo seguro

### Paso 4: Configurar en .env
```bash
# Credenciales Limitless
LIMITLESS_API_KEY=tu_token_id
LIMITLESS_API_SECRET=tu_base64_secret

# Private key de la wallet (para firmar ordenes EIP-712)
LIMITLESS_PRIVATE_KEY=0xabc123...

# Opcional: URL del API
LIMITLESS_API_URL=https://api.limitless.exchange
```

### Paso 5: Verificar Conexion
```bash
pip install limitless-sdk

python -c "
import asyncio
import os
from limitless_sdk import Client, HMACCredentials

async def test():
    client = Client(
        base_url='https://api.limitless.exchange',
        hmac_credentials=HMACCredentials(
            token_id=os.environ['LIMITLESS_API_KEY'],
            secret=os.environ['LIMITLESS_API_SECRET'],
        ),
    )
    markets = await client.markets.get_active_markets()
    print(f'Mercados activos: {len(markets[\"data\"])}')
    await client.close()

asyncio.run(test())
"
```

### URLs de Limitless
| Servicio | URL |
|----------|-----|
| REST API | `https://api.limitless.exchange` |
| WebSocket | `wss://ws.limitless.exchange` |
| Chain | Base (chainId: 8453) |
| EIP-712 Domain | `Limitless CTF Exchange` v1 |

### Notas Importantes
- Limitless es **on-chain** - las ordenes se firman con EIP-712
- **0% commission** en la mayoria de mercados
- Gas fee en Base es ~$0.01-0.02 por transaccion
- El API token usa **HMAC-SHA256** (no RSA como Kalshi)
- Timestamp debe estar dentro de **30 segundos** del servidor
- Direccion Ethereum debe ser **checksummed** (EIP-55)
- USDC usa **6 decimales**

---

## 3. Configuracion del Bot

### .env Completo (ambas plataformas)
```bash
# === BASE DE DATOS ===
DB_HOST=localhost
DB_PORT=5432
DB_NAME=trading_bot
DB_USER=trading_user
DB_PASSWORD=trading_password

# === MOTOR DE TRADING ===
TRADING_MODE=paper
EXECUTION_TYPE=simulation

# === WORKERS ===
WORKER1_ENABLED=false
WORKER1_FEEDER_TYPE=alpaca
WORKER1_SYMBOL=BTC/USD

# Worker 2: Cross-Platform Arbitrage (Kalshi + Limitless)
WORKER2_ENABLED=true
WORKER2_FEEDER_TYPE=limitless
WORKER2_SYMBOL=fed-rate-july-2026

# Worker 3: Sports Arbitrage (Limitless)
WORKER3_ENABLED=true
WORKER3_FEEDER_TYPE=limitless_sports
WORKER3_SYMBOL=SPORTS

# Worker 4: Binary Arb (Oracle Momentum)
WORKER4_ENABLED=true
WORKER4_FEEDER_TYPE=binary_arb
WORKER4_SYMBOL=BINARY_ARB

# === KALSHI ===
KALSHI_API_KEY_ID=tu_api_key_id
KALSHI_PRIVATE_KEY_PATH=/ruta/a/kalshi_key.pem
KALSHI_ENV=demo

# === LIMITLESS ===
LIMITLESS_API_KEY=tu_token_id
LIMITLESS_API_SECRET=tu_base64_secret
LIMITLESS_PRIVATE_KEY=0xabc123...

# === ARBITRAJE CROSS-PLATFORM ===
MIN_ARB_EDGE_PCT=0.03
ARB_POSITION_SIZE_PCT=0.5

# === SECURITY ===
MAX_DAILY_LOSS_USD=50.0
MAX_DRAWDOWN_PCT=0.05
MAX_CONCURRENT_POSITIONS=3
```

### Orden de Ejecucion
1. `docker-compose up -d` (inicia PostgreSQL)
2. `python main.py` (inicia backend + frontend)
3. Abrir http://localhost:8080
4. Configurar Workers 2, 3, 4 desde la UI
5. Monitorear por 2-4 semanas en modo paper

---

## 4. Flujo de Arbitraje Cross-Platform

```
Kalshi (Order Book) ←→ CrossPlatformTracker ←→ Limitless (Order Book)
                              ↓
                    Detecta: YES_K + NO_L < $1.00
                              ↓
                    Ejecuta: BUY YES en Kalshi + BUY NO en Limitless
                              ↓
                    Resolucion: 1 lado paga $1.00 → Profit = $1.00 - total_cost
```

### Requisitos
- Cuentas fondadas en AMBAS plataformas simultaneamente
- Capital minimo: $500 por plataforma ($1000 total)
- Latencia de ejecucion: <500ms entre legs
- Monitoreo constante de resolution rules

---

## 5. Errores Comunes

| Error | Causa | Solucion |
|-------|-------|----------|
| Kalshi 401 Unauthorized | API key incorrecta o timestamp viejo | Verificar key ID + sync NTP |
| Kalshi 403 | Permisos insuficientes | Regenerate key con Read+Trade |
| Limitless HMAC error | Secret incorrecto o timestamp fuera de rango | Verificar secret + sync NTP |
| Limitless EIP-712 error | Private key no coincide con wallet | Verificar PRIVATE_KEY |
| Sin liquidez | Mercado muy thin | Usar mercados con alto volumen |
| Resolution mismatch | Diferentes criterios en cada plataforma | Leer resolution rules de AMBOS |
