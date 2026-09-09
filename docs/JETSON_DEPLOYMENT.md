# Despliegue Permanente en NVIDIA Jetson Nano & CI/CD Auto-Deploy

Este documento describe la arquitectura, configuración, despliegue y flujo de CI/CD continuo del bot de arbitraje puro en el servidor físico **NVIDIA Jetson Nano**.

---

## 1. Especificaciones del Hardware y Entorno

* **Dispositivo:** NVIDIA Jetson Nano Developer Kit (B01)
* **Memoria:** 4 GB LPDDR4 compartida con GPU Maxwell
* **Arquitectura:** ARM64 (`aarch64`)
* **Sistema Operativo:** Ubuntu 18.04.6 LTS (Bionic Beaver)
* **Kernel & BSP:** Linux4Tegra `4.9.337-tegra` (L4T R32.7.6)
* **Red Local (LAN):** `192.168.10.10` (MAC: `d0:37:45:b0:f0:57`, DHCP dinámico / asignación NVIDIA)
  * **Puerto 8080:** FastAPI Backend & Dashboard Web (`http://192.168.10.10:8080`)
  * **Puerto 5432:** Base de datos PostgreSQL 16 Alpine
  * **Puerto 22:** Acceso SSH administrativo (`lvant@192.168.10.10`)

---

## 2. Arquitectura de Contenedores Docker

El sistema corre en contenedores orquestados con `docker-compose.yml`:

```
┌─────────────────────────────────────────────────────────────┐
│                    NVIDIA Jetson Nano                       │
│                                                             │
│   [systemd: bot-autodeploy]                                 │
│          │ (vigila git fetch cada 30s)                      │
│          ▼                                                  │
│   [Docker Engine: restart: unless-stopped]                  │
│     ├── trading_bot_db (PostgreSQL 16 Alpine :5432)         │
│     │     └── Volumen persistente: pgdata_trading           │
│     └── trading_bot_backend (FastAPI / Uvicorn :8080)       │
│           ├── Volumen de código: ./backend/src:/app/src     │
│           ├── Variables: .env (Modo Observación estricto)   │
│           └── Volumen web: ./web:/app/web                   │
└─────────────────────────────────────────────────────────────┘
```

### Política de Resiliencia (`restart: unless-stopped`)
Ambos contenedores tienen configurada la política `restart: unless-stopped`. Si la Jetson Nano se reinicia por corte de energía o mantenimiento, Docker revive la base de datos y el backend automáticamente al arrancar el sistema operativo.

---

## 3. Flujo de CI/CD: Auto-Deploy Nativo con `systemd`

### ¿Por qué esta solución?
* **Incompatibilidad de GLIBC en Ubuntu 18.04:** Los runners modernos de GitHub Actions (Node 20) requieren `GLIBC_2.28+`, mientras que Ubuntu 18.04 posee `GLIBC_2.27`. Actualizar GLIBC en el host compromete los drivers privativos de NVIDIA Tegra.
* **Consumo de recursos:** Un runner en Docker consume ~200 MB de RAM y requiere tokens que caducan.
* **Solución de Grado de Producción:** El servicio `bot-autodeploy.service` corre en segundo plano gestionado por `systemd`, consumiendo **0 MB de RAM adicional** y 0% de CPU.

### Componentes de CI/CD

1. **Daemon de Monitoreo:** [`backend/scripts/auto_deploy.sh`](file:///C:/Users/User/Downloads/auto_trade/backend/scripts/auto_deploy.sh)
   * Realiza un `git fetch origin feat/executable-arbitrage-engine` cada 30 segundos (consulta de metadata ultraliviana de ~100 bytes).
   * Compara el commit local (`HEAD`) con el remoto (`origin`).
   * Si detecta un nuevo push: ejecuta `git pull` y `docker restart trading_bot_backend` de forma desatendida.
2. **Instalador:** [`backend/scripts/install_autodeploy.sh`](file:///C:/Users/User/Downloads/auto_trade/backend/scripts/install_autodeploy.sh)
   * Registra el servicio `bot-autodeploy.service` en `/etc/systemd/system/`.
   * Habilita el servicio para arranque automático en el boot (`systemctl enable`).

### Comandos de Operación del Servicio
```bash
# Ver estado del auto-deploy
sudo systemctl status bot-autodeploy.service

# Ver logs en vivo del auto-deploy
sudo journalctl -u bot-autodeploy.service -f

# Reiniciar servicio
sudo systemctl restart bot-autodeploy.service
```

---

## 4. Modo de Operación y Seguridad de Capital

* **Regla Absoluta:** `ALLOWED_REAL_WORKERS=""` en `.env`.
* Todos los workers operan en **Modo Observación**.
* Ninguna orden es enviada a los exchanges; las oportunidades viables se registran en `edge_snapshots` para cálculo de Paper PnL.
* **Integración de Telegram:**
  * Worker 2 (Cross-Platform), Worker 3 (Sports Arb), Worker 6 (Maker 2-Leg), Workers 7 y 8 (Resolution Sniper) envían alertas enriquecidas con detalle de patas, liquidez y edge neto a Telegram.
