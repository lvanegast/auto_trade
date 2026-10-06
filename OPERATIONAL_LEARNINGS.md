# OPERATIONAL_LEARNINGS.md — Memoria Operativa y Reglas de Aprendizaje del Bot

> **DOCUMENTO DE CONSULTA OBLIGATORIA PARA TODOS LOS AGENTES Y DESARROLLADORES.**
> Cada error, ajuste de parámetros o lección aprendida en producción con capital real DEBE documentarse en este archivo.
> **Olvidar un aprendizaje previo o repetir un error cuesta dinero real.**

---

## 1. Reglas Inquebrantables de Configuración

### 🔴 `MAX_CONCURRENT_POSITIONS >= 2` (NUNCA 1)
* **El Error Histórico:** Se configuró `MAX_CONCURRENT_POSITIONS=1` pensando que limitaba el sistema a "1 mercado a la vez".
* **La Consecuencia:** En arbitraje puro (1xN bilateral), cada oportunidad requiere como mínimo **2 patas simultáneas** (`Pata YES` + `Pata NO`). Al ejecutarse la Pata 1, la tabla `positions` pasa a tener 1 posición abierta. Cuando la Pata 2 llega milisegundos después, `SecurityGuard` ve `1/1` posiciones y **aborta la Pata 2**. El bot queda con una pierna direccional "desnuda" sin cobertura, perdiendo la garantía de ganancia al settlement.
* **La Regla Estricta:**
  * `MAX_CONCURRENT_POSITIONS` DEBE SER COMO MÍNIMO **`2`** (para 1 mercado de 2 patas) o preferiblemente **`4`** (para permitir que mientras un mercado de 15m/1h expira o liquida, el bot pueda cotizar en otro).
  * Debe coincidir en `.env` local, en `.env` de la Jetson Nano y en la tabla `bot_state` de PostgreSQL (`key='MAX_CONCURRENT_POSITIONS'`).

### 🔴 `ALLOWED_REAL_WORKERS` (Defensa en 2 Capas)
* Todos los workers operan en `observation_only=True` por defecto.
* NINGÚN worker puede emitir órdenes reales al CLOB ni gastar capital a menos que su ID esté explícitamente en `ALLOWED_REAL_WORKERS` (ej. `ALLOWED_REAL_WORKERS=worker_6`).
* La validación se hace tanto en la estrategia como en el supervisor (`_execute_order`).

---

## 2. Mecánica de Órdenes y Fricción en Limitless (Base L2)

### Fricción de Gas en Órdenes Maker (CLOB)
* **Las órdenes Maker GTC (post-only) se firman off-chain (EIP-712):** Publicar o cancelar órdenes límite en el libro de Limitless **NO consume gas on-chain en Base**.
* **El gas se consume únicamente en:** Liquidaciones on-chain (`redeem` de contratos ganadores) y transacciones de smart contracts.
* **Lección de `FillGuard`:** No sumar gas on-chain prohibitivo como requisito previo para colocar órdenes GTC Maker, ya que bloquea carteras de prueba innecesariamente.

### Micro-Capital y Tamaño Mínimo de Órdenes
* **Límite mínimo técnico en Limitless CLOB:** `$0.15` a `$0.20 USD` por pata para evitar rechazos por redondeo de micro-shares.
* **Configuración óptima de Worker 6:**
  * `CRYPTO_LEG_MIN_USD=0.20`
  * `CRYPTO_LEG_MAX_USD=0.20`
  * `CRYPTO_MAKER_POSITION_SIZE_USD=0.20`
  * Costo total de ambas patas: **`$0.40 USD`** por operación.
* **Saldo requerido en wallet:** Un saldo de `$3.00` a `$5.00 USDC` es ideal para operar con holgura manteniendo margen de reserva líquida.

---

## 3. Modelo Cuantitativo Avellaneda-Stoikov (Worker 6)

### Filtro de Asimetría (*Skew* $0.20 \le FV \le 0.80$)
* Si el Fair Value de un evento binario está por debajo de $0.20$ o por encima de $0.80$, el mercado está prácticamente decidido.
* **Riesgo:** Si un bot cotiza pasivamente en esos extremos, operadores informados tomarán la pata barata y nadie tomará la pata cara, dejando al bot con inventario tóxico.
* **Regla:** Worker 6 rechaza cotizaciones fuera del rango $[0.20, 0.80]$.

### Filtro Estricto de Duración (Solo Intradía 15m y 1h)
* Solo se cotizan mercados de **15 minutos** y **1 hora** (`-15-min-`, `-hourly-`).
* Se descartan mercados ultra-rápidos de 5m (demasiado volátiles para órdenes maker) y mercados diarios o semanales (capital retenido demasiado tiempo sin rotación).

### Protección contra *Adverse Selection* (Binance Spot Jump)
* Si el spot líder de Binance (BTC, ETH, SOL, XRP) se mueve $>10\text{ bps}$ en $<500\text{ ms}$, Worker 6 pausa cotizaciones maker durante 15 segundos para no ser arbitrado por HFT takers más rápidos.

---

## 4. Resolution Sniper (Workers 7, 8 y 9)

### Asimetría del Sniper y Disciplina de Inactividad
* El sniper compra contratos YES a $[0.975, 0.980]$ pre-settlement para cobrar $\$1.0000$ al vencer (ganancia de $+2.0\%$ a $+2.5\%$).
* Si pierde un solo contrato, pierde el $100\%$ del principal invertido ($\approx 40$ victorias para recuperar 1 pérdida).
* **Lección crítica:** La inactividad de los snipers durante horas o días **NO ES UN FALLO**. Es la preservación matemática de capital. Si el bot comprara a $0.95$ o $0.99$ con tiempo lejano, se autodestruiría a largo plazo.

---

## 5. Infraestructura y Despliegue (NVIDIA Jetson Nano)

* **Servidor Físico:** NVIDIA Jetson Nano 4GB ARM64 (`192.168.10.10`).
* **Daemon CI/CD:** `bot-autodeploy.service` consulta `git fetch` cada 30 segundos. Si detecta nuevo commit en `feat/executable-arbitrage-engine`, actualiza y reinicia el contenedor `trading_bot_backend` de forma desatendida.
* **Contenedores:** Configurados con `restart: unless-stopped`. Resisten cortes de energía y micro-reinicios.
* **Sincronizador de Balance:** Consulta cada 60s el contrato de USDC en Base (`0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913`) para la wallet del bot (`0x247868fF939D5E9791364cDD4C2Ee11f1Dc5c6Bd`).

---

## 6. Historial de Decisiones y Ajustes

| Fecha | Componente | Decisión / Corrección | Justificación |
|---|---|---|---|
| **13-Sep-2026** | `SecurityGuard` | Elevar `MAX_CONCURRENT_POSITIONS` a 2-4 | Evitar que se aborte la segunda pata de una canasta de arbitraje. |
| **28-Sep-2026** | `Worker 6` | Forzar contratos intradía 15m / 1h | Eliminar retención de capital en diarios/semanales. |
| **30-Sep-2026** | `Supervisor` | Auto-sync de balance USDC en Base cada 60s | Mantener `portfolio_state` actualizado sin intervención manual. |
| **02-Oct-2026** | `FillGuard` | Cancelar órdenes GTC en vez de forzar venta | Las órdenes post-only no ejecutadas no son tokens poseídos; se cancelan, no se venden. |
| **05-Oct-2026** | `Recarga Base` | Fondear wallet con $3.42 USDC | Superar el umbral mínimo de capital de $0.4510 de FillGuard. |
| **05-Oct-2026** | `.env` & DB | Sincronizar `MAX_CONCURRENT_POSITIONS=4` | Garantizar coexistencia de ambas patas YES y NO en vivo. |
