from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from src.database import DatabaseManager
from src.engine import TradingEngine

# Inicializar Base de Datos
db = DatabaseManager()

# Inicializar FastAPI
app = FastAPI(
    title="Trading Bot API",
    description="API para el control y monitoreo del Bot de Trading",
)

# Permitir CORS para desarrollo local de la UI
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Guardar instancia del motor de trading en el estado de la aplicación
engine = TradingEngine(db)


@app.on_event("startup")
async def startup_event():
    # El bot iniciará apagado por defecto, el usuario debe activarlo desde la UI
    db.set_state("bot_running", "false")
    db.log("INFO", "API Backend de FastAPI iniciada y lista para recibir comandos.")


@app.on_event("shutdown")
async def shutdown_event():
    await engine.stop()
    db.log("INFO", "API Backend detenida. El bot se ha apagado de forma segura.")


@app.get("/api/status")
async def get_status():
    """Obtiene el estado actual del bot, el portafolio y precios reales/simulados."""
    try:
        is_running = engine.is_running
        portfolio = db.get_portfolio()

        # Formatear balance
        balances = {item["asset"]: float(item["free_balance"]) for item in portfolio}

        # Obtener último precio registrado en la estrategia
        last_price = 0.0
        if len(engine.strategy.prices_df) > 0:
            last_price = float(engine.strategy.prices_df.iloc[-1]["price"])
        else:
            last_price = 100.0  # Precio base inicial

        return {
            "status": "ONLINE" if is_running else "OFFLINE",
            "trading_mode": db.get_state("trading_mode", "paper").upper(),
            "last_price": last_price,
            "portfolio": balances,
            "symbol": engine.symbol,
            "base_asset": engine.base_asset,
            "quote_asset": engine.quote_asset,
            "feeder_type": engine.feeder_type,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/trades")
async def get_trades(limit: int = 50):
    """Retorna el historial de transacciones realizadas."""
    try:
        trades = db.get_trades(limit=limit)
        # Convertir objetos decimales/fechas a tipos de datos serializables
        formatted_trades = []
        for t in trades:
            formatted_trades.append(
                {
                    "id": t["id"],
                    "timestamp": t["timestamp"].isoformat(),
                    "symbol": t["symbol"],
                    "side": t["side"],
                    "price": float(t["price"]),
                    "amount": float(t["amount"]),
                    "total": float(t["total"]),
                    "status": t["status"],
                }
            )
        return formatted_trades
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/logs")
async def get_logs(limit: int = 50):
    """Retorna los últimos registros de logs."""
    try:
        logs = db.get_logs(limit=limit)
        formatted_logs = []
        for log in logs:
            formatted_logs.append(
                {
                    "id": log["id"],
                    "timestamp": log["timestamp"].isoformat(),
                    "level": log["level"],
                    "message": log["message"],
                }
            )
        return formatted_logs
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/start")
async def start_bot():
    """Inicia el bot de trading."""
    if engine.is_running:
        return {"message": "El bot ya está corriendo."}

    await engine.start()
    return {"message": "Bot iniciado exitosamente."}


@app.post("/api/stop")
async def stop_bot():
    """Detiene el bot de trading."""
    if not engine.is_running:
        return {"message": "El bot ya está apagado."}

    await engine.stop()
    return {"message": "Bot detenido exitosamente."}


# Servir archivos estáticos del frontend en la raíz
app.mount("/", StaticFiles(directory="web", html=True), name="web")
