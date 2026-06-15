from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import pandas as pd
import asyncio
from src.database import DatabaseManager
from src.engine import TradingEngine
from src.events import SignalEvent

# Inicializar Base de Datos
db = DatabaseManager()

# Inicializar FastAPI
app = FastAPI(title="Trading Bot API", description="API para el control y monitoreo del Bot de Trading")

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
    # El bot iniciará apagado por defecto
    db.set_state("bot_running", "false")
    db.log("INFO", "API Backend de FastAPI iniciada y lista para recibir comandos.")

@app.on_event("shutdown")
async def shutdown_event():
    await engine.stop()
    db.log("INFO", "API Backend detenida. El bot se ha apagado de forma segura.")

@app.get("/api/workers")
async def get_workers():
    """Retorna el listado de workers activos y su configuración."""
    res = []
    for wid, worker in engine.workers.items():
        res.append({
            "worker_id": wid,
            "name": worker.name,
            "symbol": worker.symbol,
            "feeder_type": worker.feeder_type,
            "is_running": worker.is_running,
            "base_asset": worker.base_asset,
            "quote_asset": worker.quote_asset
        })
    return res

@app.get("/api/status")
async def get_status(worker_id: str = "worker_1"):
    """Obtiene el estado actual de un worker específico, el portafolio, indicadores y precios."""
    try:
        if worker_id not in engine.workers:
            raise HTTPException(status_code=404, detail=f"Worker {worker_id} no encontrado")
            
        worker = engine.workers[worker_id]
        is_running = worker.is_running
        portfolio = db.get_portfolio()
        
        # Formatear balance
        balances = {item['asset']: float(item['free_balance']) for item in portfolio}
        
        # Obtener último precio registrado en la estrategia
        last_price = 0.0
        if len(worker.strategy.prices_df) > 0:
            last_price = float(worker.strategy.prices_df.iloc[-1]['price'])
        else:
            last_price = 0.50 if worker.feeder_type == "kalshi" else 100.0
            
        # Calcular indicadores en tiempo real
        indicators = {"ema_short": 0.0, "ema_long": 0.0, "rsi": 0.0}
        if len(worker.strategy.prices_df) >= 2:
            try:
                df_ind = worker.strategy.calculate_indicators()
                if not df_ind.empty:
                    last_row = df_ind.iloc[-1]
                    indicators["ema_short"] = float(last_row.get("ema_short", 0.0))
                    indicators["ema_long"] = float(last_row.get("ema_long", 0.0))
                    indicators["rsi"] = float(last_row.get("rsi", 0.0))
            except Exception as e:
                print("Error calculating indicators for API status:", e)

        # Obtener precio de entrada promedio (avg_entry_price)
        avg_entry_price = 0.0
        if worker.alpaca_client:
            try:
                symbol_clean = worker.symbol.replace("/", "").upper()
                pos = worker.alpaca_client.get_open_position(symbol_clean)
                avg_entry_price = float(pos.avg_entry_price)
            except Exception:
                pass
        else:
            try:
                trades_list = db.get_trades(limit=15, worker_id=worker_id)
                completed_buys = [t for t in trades_list if t["side"].upper() == "BUY" and t["status"].upper() in ["COMPLETED", "FILLED"]]
                if completed_buys:
                    avg_entry_price = float(completed_buys[0]["price"])
            except Exception:
                pass

        return {
            "status": "ONLINE" if is_running else "OFFLINE",
            "trading_mode": db.get_state("trading_mode", "paper").upper(),
            "last_price": last_price,
            "portfolio": balances,
            "symbol": worker.symbol,
            "base_asset": worker.base_asset,
            "quote_asset": worker.quote_asset,
            "feeder_type": worker.feeder_type,
            "name": worker.name,
            "last_position": worker.strategy.last_position,
            "avg_entry_price": avg_entry_price,
            "indicators": indicators
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/trades")
async def get_trades(limit: int = 50, worker_id: str = None):
    """Retorna el historial de transacciones realizadas."""
    try:
        trades = db.get_trades(limit=limit, worker_id=worker_id)
        formatted_trades = []
        for t in trades:
            formatted_trades.append({
                "id": t["id"],
                "timestamp": t["timestamp"].isoformat(),
                "symbol": t["symbol"],
                "side": t["side"],
                "price": float(t["price"]),
                "amount": float(t["amount"]),
                "total": float(t["total"]),
                "status": t["status"],
                "external_order_id": t["external_order_id"]
            })
        return formatted_trades
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/logs")
async def get_logs(limit: int = 50, worker_id: str = None):
    """Retorna los últimos registros de logs."""
    try:
        logs = db.get_logs(limit=limit, worker_id=worker_id)
        formatted_logs = []
        for log in logs:
            formatted_logs.append({
                "id": log["id"],
                "timestamp": log["timestamp"].isoformat(),
                "level": log["level"],
                "message": log["message"]
            })
        return formatted_logs
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/start")
async def start_bot(worker_id: str = None):
    """Inicia el bot de trading para un worker o para todos."""
    if worker_id:
        if worker_id not in engine.workers:
            raise HTTPException(status_code=404, detail=f"Worker {worker_id} no encontrado")
        worker = engine.workers[worker_id]
        if worker.is_running:
            return {"message": f"El worker {worker_id} ya está corriendo."}
        await engine.start(worker_id)
        return {"message": f"Worker {worker_id} iniciado exitosamente."}
    else:
        await engine.start()
        return {"message": "Todos los workers iniciados exitosamente."}

@app.post("/api/stop")
async def stop_bot(worker_id: str = None):
    """Detiene el bot de trading para un worker o para todos."""
    if worker_id:
        if worker_id not in engine.workers:
            raise HTTPException(status_code=404, detail=f"Worker {worker_id} no encontrado")
        worker = engine.workers[worker_id]
        if not worker.is_running:
            return {"message": f"El worker {worker_id} ya está apagado."}
        await engine.stop(worker_id)
        return {"message": f"Worker {worker_id} detenido exitosamente."}
    else:
        await engine.stop()
        return {"message": "Todos los workers detenidos exitosamente."}

@app.post("/api/order")
async def place_manual_order(body: dict):
    """Envía una orden de compra o venta manual para un worker."""
    worker_id = body.get("worker_id", "worker_1")
    side = body.get("side", "BUY").upper()
    qty = body.get("qty") or body.get("amount")
    amount = float(qty) if qty is not None else None
    
    if worker_id not in engine.workers:
        raise HTTPException(status_code=404, detail="Worker no encontrado")
        
    worker = engine.workers[worker_id]
    if not worker.is_running:
        raise HTTPException(status_code=400, detail="El worker debe estar encendido (ONLINE) para ejecutar órdenes")
        
    # Obtener el precio actual
    price = 0.0
    if len(worker.strategy.prices_df) > 0:
        price = float(worker.strategy.prices_df.iloc[-1]['price'])
    else:
        price = 0.50 if worker.feeder_type == "kalshi" else 100.0
        
    signal = SignalEvent(
        symbol=worker.symbol,
        side=side,
        price=price,
        reason="Orden manual colocada por el usuario desde el Dashboard",
        amount=amount
    )
    
    # Encolar para ejecución inmediata
    await worker.queue.put(signal)
    return {"message": f"Orden manual de {side} enviada exitosamente para {worker.symbol}"}

@app.post("/api/order/cancel")
async def cancel_order(body: dict):
    """Cancela una orden activa en Alpaca por su ID externo y actualiza la base de datos."""
    worker_id = body.get("worker_id", "worker_1")
    external_order_id = body.get("external_order_id")
    
    if not external_order_id:
        raise HTTPException(status_code=400, detail="Se requiere el ID de orden externo (external_order_id)")
        
    if worker_id not in engine.workers:
        raise HTTPException(status_code=404, detail="Worker no encontrado")
        
    worker = engine.workers[worker_id]
    if not worker.alpaca_client:
        # Si no hay cliente real de Alpaca, cancelamos localmente en la base de datos
        db.update_trade_status(external_order_id, "CANCELED")
        db.log("INFO", f"Orden simulada {external_order_id} cancelada localmente.", worker_id)
        return {"message": "Orden simulada cancelada con éxito."}
        
    try:
        import uuid
        # Llamar a Alpaca
        await asyncio.to_thread(worker.alpaca_client.cancel_order_by_id, uuid.UUID(external_order_id))
        db.update_trade_status(external_order_id, "CANCELED")
        db.log("INFO", f"Orden {external_order_id} cancelada con éxito en Alpaca.", worker_id)
        # Sincronizar balances inmediatamente
        await worker._sync_alpaca_portfolio()
        return {"message": "Orden cancelada con éxito en Alpaca."}
    except Exception as e:
        # En caso de error, también intentamos actualizar localmente por si ya fue cancelada
        db.update_trade_status(external_order_id, "CANCELED")
        db.log("WARNING", f"Fallo al cancelar orden en Alpaca: {e}. Se forzó cancelación local en base de datos.", worker_id)
        return {"message": f"Orden marcada como cancelada. Nota: {e}"}

@app.post("/api/worker/config")
async def configure_worker(body: dict):
    """Permite cambiar el símbolo del worker dinámicamente."""
    worker_id = body.get("worker_id", "worker_1")
    symbol = body.get("symbol")
    
    if not symbol:
        raise HTTPException(status_code=400, detail="Se requiere especificar el nuevo símbolo")
        
    if worker_id not in engine.workers:
        raise HTTPException(status_code=404, detail="Worker no encontrado")
        
    worker = engine.workers[worker_id]
    
    # Detener el worker si está corriendo
    was_running = worker.is_running
    if was_running:
        await engine.stop(worker_id)
        
    try:
        # Actualizar el símbolo del worker
        worker.symbol = symbol.upper()
        worker.base_asset, worker.quote_asset = worker._parse_symbol()
        
        # Inicializar el feeder correspondiente con el nuevo símbolo
        from src.feeders.mock_feeder import MockFeeder
        from src.feeders.oanda_feeder import OandaFeeder
        from src.feeders.ig_feeder import IGFeeder
        from src.feeders.alpaca_feeder import AlpacaFeeder
        from src.feeders.kalshi_feeder import KalshiFeeder
        
        if worker.feeder_type == "oanda":
            worker.feeder = OandaFeeder(worker.symbol, worker.queue)
        elif worker.feeder_type == "ig":
            worker.feeder = IGFeeder(worker.symbol, worker.queue)
        elif worker.feeder_type == "alpaca":
            worker.feeder = AlpacaFeeder(worker.symbol, worker.queue)
        elif worker.feeder_type == "kalshi":
            worker.feeder = KalshiFeeder(worker.symbol, worker.queue)
        else:
            worker.feeder = MockFeeder(worker.symbol, worker.queue, interval=1.0)
            
        # Re-inicializar la estrategia con el nuevo símbolo
        from src.strategy.ema_rsi import EmaRsiStrategy
        worker.strategy = EmaRsiStrategy(worker.symbol)
        
        # Si tiene cliente Alpaca y la ejecución es real/paper (no simulación), pre-cargar historial
        if worker.alpaca_client:
            await worker._warm_up_strategy()
            
        # Si estaba corriendo, volver a iniciar
        if was_running:
            await engine.start(worker_id)
            
        db.log("INFO", f"Símbolo del worker {worker_id} cambiado dinámicamente a {worker.symbol}", worker_id)
        return {"message": f"Símbolo del worker cambiado con éxito a {worker.symbol}"}
    except Exception as e:
        db.log("ERROR", f"Error al cambiar símbolo del worker {worker_id}: {e}", worker_id)
        raise HTTPException(status_code=500, detail=f"Fallo al reconfigurar el activo: {e}")

# Servir archivos estáticos del frontend en la raíz
app.mount("/", StaticFiles(directory="web", html=True), name="web")
