from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import asyncio
import os
from src.database import DatabaseManager
from src.engine import TradingEngine
from src.events import SignalEvent
from src.security import security_guard
from src.websocket_server import ws_server, make_event

# Inicializar Base de Datos
db = DatabaseManager()
security_guard.set_db(db)

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
    # Configuración para auto-iniciar el bot al encender el contenedor (por defecto true)
    auto_start = os.getenv("AUTO_START", "true").lower() == "true"
    if auto_start:
        db.set_state("bot_running", "true")
        try:
            await engine.start()
            db.log(
                "INFO",
                "El bot de trading se ha iniciado AUTOMÁTICAMENTE al arrancar el backend.",
            )
        except Exception as e:
            db.log("ERROR", f"Error en el auto-inicio del bot: {e}")
    else:
        db.set_state("bot_running", "false")
        db.log(
            "INFO",
            "API Backend de FastAPI iniciada y lista para recibir comandos (Auto-start desactivado).",
        )


@app.on_event("shutdown")
async def shutdown_event():
    await engine.stop()
    db.log("INFO", "API Backend detenida. El bot se ha apagado de forma segura.")


@app.get("/api/workers")
async def get_workers():
    """Retorna el listado de workers activos y su configuración."""
    res = []
    for wid, worker in engine.workers.items():
        res.append(
            {
                "worker_id": wid,
                "name": worker.name,
                "symbol": worker.symbol,
                "feeder_type": worker.feeder_type,
                "is_running": worker.is_running,
                "base_asset": worker.base_asset,
                "quote_asset": worker.quote_asset,
            }
        )
    return res


@app.get("/api/status")
async def get_status(worker_id: str = "worker_1"):
    """Obtiene el estado actual de un worker específico, el portafolio, indicadores y precios."""
    try:
        if worker_id not in engine.workers:
            raise HTTPException(
                status_code=404, detail=f"Worker {worker_id} no encontrado"
            )

        worker = engine.workers[worker_id]
        is_running = worker.is_running
        portfolio = db.get_portfolio(worker_id=worker_id)

        # Formatear balance
        balances = {item["asset"]: float(item["free_balance"]) for item in portfolio}

        # Obtener último precio registrado en la estrategia
        last_price = 0.0
        if len(worker.strategy.prices_df) > 0:
            last_price = float(worker.strategy.prices_df.iloc[-1]["price"])
        else:
            # Intentar usar el precio del último trade en la base de datos como fallback realista
            try:
                last_trades = db.get_trades(limit=1, worker_id=worker_id)
                if last_trades:
                    last_price = float(last_trades[0]["price"])
            except Exception:
                pass

            if last_price <= 0:
                last_price = 0.50 if worker.feeder_type == "kalshi" else 100.0

        # Calcular indicadores en tiempo real
        indicators = {"ema_short": 0.0, "ema_long": 0.0, "rsi": 0.0}
        if len(worker.strategy.prices_df) >= 2 and hasattr(
            worker.strategy, "calculate_indicators"
        ):
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
                completed_buys = [
                    t
                    for t in trades_list
                    if t["side"].upper() == "BUY"
                    and t["status"].upper() in ["COMPLETED", "FILLED"]
                ]
                if completed_buys:
                    avg_entry_price = float(completed_buys[0]["price"])
            except Exception:
                pass

        # Obtener historial de precios registrado en la estrategia
        price_history = []
        if len(worker.strategy.prices_df) > 0:
            has_ohlc = all(
                col in worker.strategy.prices_df.columns
                for col in ["open", "high", "low", "close"]
            )
            price_history = [
                {
                    "timestamp": row["timestamp"].strftime("%Y-%m-%d %H:%M:%S")
                    if hasattr(row["timestamp"], "strftime")
                    else str(row["timestamp"]),
                    "price": float(row["price"]),
                    "open": float(row["open"]) if has_ohlc else float(row["price"]),
                    "high": float(row["high"]) if has_ohlc else float(row["price"]),
                    "low": float(row["low"]) if has_ohlc else float(row["price"]),
                    "close": float(row["close"]) if has_ohlc else float(row["price"]),
                }
                for _, row in worker.strategy.prices_df.iterrows()
            ]

        # Obtener historial de comparación si es arbitraje cross-platform
        comparison_history = []
        if hasattr(worker.strategy, "event_id") and worker.strategy.event_id:
            # Buscar el otro worker que tenga el mismo event_id pero diferente platform
            other_worker = None
            for w_id, w in engine.workers.items():
                if (
                    w_id != worker_id
                    and hasattr(w.strategy, "event_id")
                    and w.strategy.event_id == worker.strategy.event_id
                ):
                    other_worker = w
                    break

            if other_worker and len(other_worker.strategy.prices_df) > 0:
                has_ohlc_other = all(
                    col in other_worker.strategy.prices_df.columns
                    for col in ["open", "high", "low", "close"]
                )
                comparison_history = [
                    {
                        "timestamp": row["timestamp"].strftime("%Y-%m-%d %H:%M:%S")
                        if hasattr(row["timestamp"], "strftime")
                        else str(row["timestamp"]),
                        "price": float(row["price"]),
                        "open": float(row["open"])
                        if has_ohlc_other
                        else float(row["price"]),
                        "high": float(row["high"])
                        if has_ohlc_other
                        else float(row["price"]),
                        "low": float(row["low"])
                        if has_ohlc_other
                        else float(row["price"]),
                        "close": float(row["close"])
                        if has_ohlc_other
                        else float(row["price"]),
                    }
                    for _, row in other_worker.strategy.prices_df.iterrows()
                ]

        # Obtener fecha de expiración si es un mercado de predicción con event_id
        expiration = None
        if hasattr(worker.strategy, "event_id") and worker.strategy.event_id:
            from src.strategy.market_pairs import get_pair_by_event_id

            pair = get_pair_by_event_id(worker.strategy.event_id)
            if pair:
                expiration = pair.get("expiration")

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
            "last_position": getattr(worker.strategy, "last_position", None),
            "avg_entry_price": avg_entry_price,
            "position_id": getattr(worker.strategy, "_position_id", None),
            "indicators": indicators,
            "price_history": price_history,
            "comparison_history": comparison_history,
            "expiration": expiration,
            "teorical_probability": getattr(
                worker.strategy, "teorical_probability", 0.50
            ),
            "edge": getattr(worker.strategy, "edge", 0.0),
            "kelly_recommendation": getattr(
                worker.strategy, "kelly_recommendation", 0.0
            ),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


async def _get_depth_data(worker_id: str) -> dict:
    """Obtiene datos del libro de órdenes para un worker (compartido por REST y WebSocket)."""
    if worker_id not in engine.workers:
        return {"bids": [], "asks": []}

    worker = engine.workers[worker_id]
    symbol = worker.symbol
    feeder_type = worker.feeder_type

    import requests

    if feeder_type == "binance":
        try:
            symbol_clean = symbol.replace("/", "").upper()
            url = f"https://api.binance.com/api/v3/depth?symbol={symbol_clean}&limit=20"
            res = await asyncio.to_thread(requests.get, url, timeout=5)
            if res.status_code == 200:
                data = res.json()
                return {
                    "bids": [[float(b[0]), float(b[1])] for b in data.get("bids", [])],
                    "asks": [[float(a[0]), float(a[1])] for a in data.get("asks", [])],
                }
            else:
                print(f"[Depth API] Binance status {res.status_code}, falling back.")
        except Exception as e:
            print(f"[Depth API] Binance error: {e}, falling back.")

    elif feeder_type == "polymarket":
        try:
            url = f"https://clob.polymarket.com/book?token_id={symbol}"
            res = await asyncio.to_thread(requests.get, url, timeout=5)
            if res.status_code == 200:
                data = res.json()
                return {
                    "bids": [
                        [float(b["price"]), float(b["size"])]
                        for b in data.get("bids", [])
                    ],
                    "asks": [
                        [float(a["price"]), float(a["size"])]
                        for a in data.get("asks", [])
                    ],
                }
            else:
                print(f"[Depth API] Polymarket status {res.status_code}, falling back.")
        except Exception as e:
            print(f"[Depth API] Polymarket error: {e}, falling back.")

    # Fallback for alpaca, oanda, kalshi, mock, or failed API calls
    try:
        last_price = 0.0
        if len(worker.strategy.prices_df) > 0:
            last_price = float(worker.strategy.prices_df.iloc[-1]["price"])
        else:
            try:
                last_trades = db.get_trades(limit=1, worker_id=worker_id)
                if last_trades:
                    last_price = float(last_trades[0]["price"])
            except Exception:
                pass

            if last_price <= 0:
                last_price = 0.50 if feeder_type in ["kalshi", "polymarket"] else 100.0

        import random

        # Usar bid/ask reales del último quote si están disponibles
        real_bid = getattr(worker, "last_bid", 0.0)
        real_ask = getattr(worker, "last_ask", 0.0)
        if real_bid > 0 and real_ask > 0 and real_ask > real_bid:
            spread = real_ask - real_bid
            mid = (real_bid + real_ask) / 2.0
        else:
            spread = last_price * 0.0006
            mid = last_price

        bids = []
        asks = []
        for i in range(1, 15):
            bid_price = mid - spread * 0.5 - (i * spread * 0.4)
            ask_price = mid + spread * 0.5 + (i * spread * 0.4)
            bid_size = random.uniform(0.5, 8.0) * (1.0 + random.uniform(-0.3, 0.3))
            ask_size = random.uniform(0.5, 8.0) * (1.0 + random.uniform(-0.3, 0.3))
            bids.append([round(bid_price, 5), round(bid_size, 4)])
            asks.append([round(ask_price, 5), round(ask_size, 4)])

        return {"bids": bids, "asks": asks}

    except Exception as e:
        print("Error generating simulated depth:", e)
        return {"bids": [], "asks": []}


@app.get("/api/depth")
async def get_depth(worker_id: str = "worker_1"):
    """Retorna las órdenes activas en el libro de órdenes (bids y asks) para el gráfico de profundidad."""
    if worker_id not in engine.workers:
        raise HTTPException(status_code=404, detail="Worker no encontrado")
    return await _get_depth_data(worker_id)


@app.get("/api/trades")
async def get_trades(limit: int = 50, worker_id: str = None):
    """Retorna el historial de transacciones realizadas."""
    try:
        trades = db.get_trades(limit=limit, worker_id=worker_id)
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
                    "external_order_id": t["external_order_id"],
                }
            )
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
async def start_bot(worker_id: str = None):
    """Inicia el bot de trading para un worker o para todos."""
    if worker_id:
        if worker_id not in engine.workers:
            raise HTTPException(
                status_code=404, detail=f"Worker {worker_id} no encontrado"
            )
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
            raise HTTPException(
                status_code=404, detail=f"Worker {worker_id} no encontrado"
            )
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
        raise HTTPException(
            status_code=400,
            detail="El worker debe estar encendido (ONLINE) para ejecutar órdenes",
        )

    # Obtener el precio actual
    price = 0.0
    if len(worker.strategy.prices_df) > 0:
        price = float(worker.strategy.prices_df.iloc[-1]["price"])
    else:
        price = 0.50 if worker.feeder_type == "kalshi" else 100.0

    signal = SignalEvent(
        symbol=worker.symbol,
        side=side,
        price=price,
        reason="Orden manual colocada por el usuario desde el Dashboard",
        amount=amount,
    )

    # Encolar para ejecución inmediata
    await worker.queue.put(signal)
    return {
        "message": f"Orden manual de {side} enviada exitosamente para {worker.symbol}"
    }


@app.post("/api/order/cancel")
async def cancel_order(body: dict):
    """Cancela una orden activa en Alpaca por su ID externo y actualiza la base de datos."""
    worker_id = body.get("worker_id", "worker_1")
    external_order_id = body.get("external_order_id")

    if not external_order_id:
        raise HTTPException(
            status_code=400,
            detail="Se requiere el ID de orden externo (external_order_id)",
        )

    if worker_id not in engine.workers:
        raise HTTPException(status_code=404, detail="Worker no encontrado")

    worker = engine.workers[worker_id]
    if not worker.alpaca_client:
        # Si no hay cliente real de Alpaca, cancelamos localmente en la base de datos
        db.update_trade_status(external_order_id, "CANCELED")
        db.log(
            "INFO",
            f"Orden simulada {external_order_id} cancelada localmente.",
            worker_id,
        )
        return {"message": "Orden simulada cancelada con éxito."}

    try:
        import uuid

        # Llamar a Alpaca
        await asyncio.to_thread(
            worker.alpaca_client.cancel_order_by_id, uuid.UUID(external_order_id)
        )
        db.update_trade_status(external_order_id, "CANCELED")
        db.log(
            "INFO",
            f"Orden {external_order_id} cancelada con éxito en Alpaca.",
            worker_id,
        )
        # Sincronizar balances inmediatamente
        await worker._sync_alpaca_portfolio()
        return {"message": "Orden cancelada con éxito en Alpaca."}
    except Exception as e:
        # En caso de error, también intentamos actualizar localmente por si ya fue cancelada
        db.update_trade_status(external_order_id, "CANCELED")
        db.log(
            "WARNING",
            f"Fallo al cancelar orden en Alpaca: {e}. Se forzó cancelación local en base de datos.",
            worker_id,
        )
        return {"message": f"Orden marcada como cancelada. Nota: {e}"}


@app.get("/api/positions")
async def get_positions(limit: int = 50, worker_id: str = None, status: str = None):
    """Retorna posiciones. status: 'OPEN', 'CLOSED', o None (todas)."""
    try:
        if status == "OPEN":
            positions = db.get_open_positions(worker_id=worker_id)
        elif status == "CLOSED":
            positions = db.get_position_history(limit=limit, worker_id=worker_id)
        else:
            positions = db.get_all_positions(limit=limit, worker_id=worker_id)
        formatted = []
        for p in positions:
            entry_time = p["entry_time"]
            close_time = p.get("close_time")
            formatted.append(
                {
                    "id": p["id"],
                    "worker_id": p["worker_id"],
                    "symbol": p["symbol"],
                    "side": p["side"],
                    "entry_price": float(p["entry_price"]),
                    "entry_lead_price": float(p["entry_lead_price"]),
                    "amount": float(p["amount"]),
                    "entry_time": entry_time.isoformat() if entry_time else None,
                    "status": p["status"],
                    "close_price": float(p["close_price"])
                    if p.get("close_price")
                    else None,
                    "close_time": close_time.isoformat() if close_time else None,
                    "close_reason": p.get("close_reason"),
                    "pnl": float(p["pnl"]) if p.get("pnl") is not None else None,
                }
            )
        return formatted
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/position/close")
async def close_position(body: dict):
    """Cierra una posición abierta manualmente."""
    worker_id = body.get("worker_id", "worker_1")
    position_id = body.get("position_id")

    if worker_id not in engine.workers:
        raise HTTPException(status_code=404, detail="Worker no encontrado")

    worker = engine.workers[worker_id]
    strategy = worker.strategy

    # Si se proporciona position_id, cerrar esa posición específica
    if position_id:
        pos = None
        for p in db.get_open_positions(worker_id=worker_id):
            if p["id"] == position_id:
                pos = p
                break
        if not pos:
            raise HTTPException(
                status_code=404, detail="Posición no encontrada o ya cerrada"
            )

        # Obtener precio actual
        price = 0.0
        if len(strategy.prices_df) > 0:
            price = float(strategy.prices_df.iloc[-1]["price"])

        # Si la posición activa del strategy coincide, cerrarla también
        if strategy._position_id == position_id and strategy.last_position is not None:
            side = "SELL" if strategy.last_position == "BUY" else "BUY"
            signal = SignalEvent(
                symbol=worker.symbol,
                side=side,
                price=price,
                reason="Cierre manual por el usuario desde el Dashboard",
                amount=float(pos["amount"]),
                position_id=position_id,
            )
            await worker.queue.put(signal)
            return {"message": f"Posición #{position_id} enviada a cerrar."}
        else:
            # Cerrar directamente en DB
            db.close_position(
                position_id, price, "Cierre manual por el usuario", worker_id=worker_id
            )
            return {"message": f"Posición #{position_id} cerrada en DB."}

    # Sin position_id: cerrar la posición activa del strategy
    if strategy.last_position is None:
        raise HTTPException(
            status_code=400, detail="No hay posición activa para cerrar"
        )

    price = 0.0
    if len(strategy.prices_df) > 0:
        price = float(strategy.prices_df.iloc[-1]["price"])

    side = "SELL" if strategy.last_position == "BUY" else "BUY"
    signal = SignalEvent(
        symbol=worker.symbol,
        side=side,
        price=price,
        reason="Cierre manual por el usuario desde el Dashboard",
    )
    await worker.queue.put(signal)
    return {"message": f"Posición {strategy.last_position} enviada a cerrar a {price}."}


@app.post("/api/worker/config")
async def configure_worker(body: dict):
    """Permite cambiar el símbolo del worker dinámicamente."""
    worker_id = body.get("worker_id", "worker_1")
    symbol = body.get("symbol")
    feeder_type = body.get("feeder_type")

    if not symbol:
        raise HTTPException(
            status_code=400, detail="Se requiere especificar el nuevo símbolo"
        )

    if worker_id not in engine.workers:
        raise HTTPException(status_code=404, detail="Worker no encontrado")

    worker = engine.workers[worker_id]

    # Detener el worker si está corriendo
    was_running = worker.is_running
    if was_running:
        await engine.stop(worker_id)

    try:
        # Actualizar tipo de feeder si se proporciona
        if feeder_type:
            worker.feeder_type = feeder_type.lower()

        # Actualizar el símbolo del worker
        worker.symbol = symbol.upper()
        worker.base_asset, worker.quote_asset = worker._parse_symbol()

        # Inicializar el feeder correspondiente con el nuevo símbolo
        from src.feeders.mock_feeder import MockFeeder
        from src.feeders.oanda_feeder import OandaFeeder
        from src.feeders.ig_feeder import IGFeeder
        from src.feeders.alpaca_feeder import AlpacaFeeder
        from src.feeders.kalshi_feeder import KalshiFeeder
        from src.feeders.binance_feeder import BinanceFeeder
        from src.feeders.polymarket_feeder import PolymarketFeeder

        if worker.feeder_type == "oanda":
            worker.feeder = OandaFeeder(worker.symbol, worker.queue)
        elif worker.feeder_type == "ig":
            worker.feeder = IGFeeder(worker.symbol, worker.queue)
        elif worker.feeder_type == "alpaca":
            worker.feeder = AlpacaFeeder(worker.symbol, worker.queue)
        elif worker.feeder_type == "kalshi":
            worker.feeder = KalshiFeeder(worker.symbol, worker.queue)
        elif worker.feeder_type == "binance":
            worker.feeder = BinanceFeeder(worker.symbol, worker.queue)
        elif worker.feeder_type == "polymarket":
            worker.feeder = PolymarketFeeder(worker.symbol, worker.queue)
        else:
            worker.feeder = MockFeeder(worker.symbol, worker.queue, interval=1.0)

        # Re-inicializar la estrategia según tipo de feeder
        if worker.feeder_type in ("kalshi", "polymarket"):
            from src.strategy.cross_platform_arb import CrossPlatformArbitrageStrategy

            worker.strategy = CrossPlatformArbitrageStrategy(
                worker.symbol,
                feeder_type=worker.feeder_type,
                db=db,
                worker_id=worker_id,
            )
        else:
            from src.strategy.lead_lag_arbitrage import LeadLagArbitrageStrategy

            worker.strategy = LeadLagArbitrageStrategy(
                worker.symbol, db=db, worker_id=worker_id
            )

        # Si tiene cliente Alpaca y la ejecución es real/paper (no simulación), pre-cargar historial
        if worker.alpaca_client and worker.feeder_type == "alpaca":
            await worker._warm_up_strategy()

        # Si estaba corriendo, volver a iniciar
        if was_running:
            await engine.start(worker_id)

        db.log(
            "INFO",
            f"Símbolo del worker {worker_id} cambiado dinámicamente a {worker.symbol} (Feeder: {worker.feeder_type})",
            worker_id,
        )
        return {"message": f"Símbolo del worker cambiado con éxito a {worker.symbol}"}
    except Exception as e:
        db.log(
            "ERROR", f"Error al cambiar símbolo del worker {worker_id}: {e}", worker_id
        )
        raise HTTPException(
            status_code=500, detail=f"Fallo al reconfigurar el activo: {e}"
        )


@app.get("/api/arbitrage")
async def get_arbitrage_opportunities():
    """Retorna todas las oportunidades de arbitraje cross-platform detectadas en tiempo real."""
    from src.strategy.cross_platform_tracker import cross_platform_tracker
    from src.strategy.market_pairs import get_active_pairs

    pairs = get_active_pairs()
    all_opportunities = cross_platform_tracker.scan_all_pairs(min_edge_pct=0.01)

    # Enriquecer con info del pair
    results = []
    for opp in all_opportunities:
        pair = next((p for p in pairs if p["event_id"] == opp["event_id"]), None)
        if pair:
            opp["event_label"] = pair["event_label"]
            opp["category"] = pair["category"]
        results.append(opp)

    # También incluir el estado de precios de todos los pares conocidos
    price_map = {}
    for pair in pairs:
        both = cross_platform_tracker.get_both_prices(pair["event_id"])
        price_map[pair["event_id"]] = {
            "event_label": pair["event_label"],
            "category": pair["category"],
            "kalshi": both.get("kalshi", {}),
            "limitless": both.get("limitless", {}),
        }

    return {
        "opportunities": results,
        "market_prices": price_map,
        "active_pairs_count": len(pairs),
    }


@app.websocket("/ws/{worker_id}")
async def websocket_endpoint(websocket: WebSocket, worker_id: str):
    """Streaming en tiempo real para un worker específico.

    Eventos enviados:
        - initial_state: estado completo al conectar
        - price_update: nuevo precio recibido
        - worker_status: cambio de estado del worker (start/stop)
        - trade_update: nuevo trade ejecutado
        - depth_update: libro de órdenes (respuesta a comando "depth")
        - log: nueva entrada de log (tiempo real)
        - heartbeat: keep-alive periódico

    Comandos aceptados del cliente:
        - "ping" → responde {"type":"pong"}
        - "depth" → responde {"type":"depth_update","data":{...}}
    """
    if worker_id not in engine.workers:
        await websocket.close(code=4004, reason="Worker no encontrado")
        return

    await ws_server.connect(websocket, worker_id)
    worker = engine.workers[worker_id]

    try:
        # Enviar estado inicial
        await _send_initial_state(websocket, worker, worker_id)

        # Mantener conexión viva con heartbeat
        while True:
            try:
                # Esperar mensajes del cliente (pings, comandos) con timeout
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                if data == "ping":
                    await websocket.send_text('{"type":"pong"}')
                elif data == "depth":
                    depth_data = await _get_depth_data(worker_id)
                    import json as json_mod

                    await websocket.send_text(
                        json_mod.dumps(
                            make_event("depth_update", depth_data), default=str
                        )
                    )
            except asyncio.TimeoutError:
                # Heartbeat: verificar que el cliente siga vivo
                try:
                    await websocket.send_text('{"type":"heartbeat"}')
                except Exception:
                    break
    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"[WS] Error en conexión WebSocket para {worker_id}: {e}")
    finally:
        await ws_server.disconnect(websocket, worker_id)


async def _send_initial_state(websocket: WebSocket, worker, worker_id: str):
    """Envía el estado inicial completo al cliente que se conecta."""
    import json as json_mod

    try:
        portfolio = db.get_portfolio(worker_id=worker_id)
        balances = {item["asset"]: float(item["free_balance"]) for item in portfolio}

        last_price = 0.0
        if len(worker.strategy.prices_df) > 0:
            last_price = float(worker.strategy.prices_df.iloc[-1]["price"])

        event = make_event(
            "initial_state",
            {
                "symbol": worker.symbol,
                "feeder_type": worker.feeder_type,
                "is_running": worker.is_running,
                "last_price": last_price,
                "portfolio": balances,
                "base_asset": worker.base_asset,
                "quote_asset": worker.quote_asset,
                "last_position": getattr(worker.strategy, "last_position", None),
                "position_id": getattr(worker.strategy, "_position_id", None),
                "teorical_probability": getattr(
                    worker.strategy, "teorical_probability", 0.50
                ),
                "edge": getattr(worker.strategy, "edge", 0.0),
                "arbitrage_opportunity": getattr(
                    worker.strategy, "last_arbitrage_opportunity", None
                ),
            },
        )
        await websocket.send_text(json_mod.dumps(event, default=str))
    except Exception as e:
        print(f"[WS] Error enviando estado inicial: {e}")


# ==========================================================================
# Security Guard Endpoints (MUST be before StaticFiles mount)
# ==========================================================================


@app.post("/api/emergency-stop")
async def emergency_stop():
    """Kill switch: stop all trading immediately and close open positions."""
    security_guard.trigger_kill_switch("Manual emergency stop via API")

    # Stop all workers
    await engine.stop()

    # Close all open positions
    open_positions = db.get_open_positions()
    closed_count = 0
    for pos in open_positions:
        try:
            close_price = float(pos.get("entry_price", 0.5))
            db.close_position(
                pos["id"], close_price, "EMERGENCY STOP", worker_id=pos["worker_id"]
            )
            closed_count += 1
        except Exception as e:
            print(f"[EmergencyStop] Error closing position {pos.get('id')}: {e}")

    db.log(
        "CRITICAL",
        f"EMERGENCY STOP ejecutado. {closed_count} posiciones cerradas. Trading detenido.",
        "ALL",
    )

    return {
        "status": "EMERGENCY_STOP",
        "positions_closed": closed_count,
        "message": "Kill switch activado. Trading detenido. Use /api/release-stop para reanudar.",
    }


@app.post("/api/release-stop")
async def release_stop():
    """Release the kill switch AND reset drawdown tracker."""
    security_guard.release_kill_switch()
    current_equity = db.get_total_equity_usd()
    security_guard._peak_equity = current_equity
    db.log(
        "INFO",
        f"Kill switch liberado. Peak equity reset a ${current_equity:.2f}.",
        "ALL",
    )
    return {
        "status": "RELEASED",
        "message": f"Kill switch liberado. Peak reset a ${current_equity:.2f}.",
    }


@app.post("/api/unpause-worker/{worker_id}")
async def unpause_worker(worker_id: str):
    """Manually unpause a worker that was auto-paused for consecutive losses."""
    security_guard.unpause_worker(worker_id)
    db.log("INFO", f"Worker {worker_id} reanudado manualmente.", worker_id)
    return {"status": "UNPAUSED", "worker_id": worker_id}


@app.get("/api/risk-metrics")
async def get_risk_metrics():
    """Returns current risk metrics for the dashboard."""
    return security_guard.get_metrics()


# ==========================================================================
# Audit Trail & P&L Endpoints
# ==========================================================================


@app.get("/api/pnl/summary")
async def get_pnl_summary(
    worker_id: str = None,
    trading_mode: str = None,
    start_date: str = None,
    end_date: str = None,
):
    """Aggregated P&L metrics (win rate, Sharpe, profit factor, etc.)."""
    return db.get_pnl_summary(
        worker_id=worker_id,
        trading_mode=trading_mode,
        start_date=start_date,
        end_date=end_date,
    )


@app.get("/api/equity-curve")
async def get_equity_curve(
    worker_id: str = None,
    start_date: str = None,
    end_date: str = None,
):
    """Portfolio equity time series for charting."""
    return db.get_equity_curve(
        worker_id=worker_id,
        start_date=start_date,
        end_date=end_date,
    )


@app.get("/api/trades/export")
async def export_trades_csv(
    worker_id: str = None,
    trading_mode: str = None,
    start_date: str = None,
    end_date: str = None,
):
    """Export trades as CSV for external audit."""
    from fastapi.responses import StreamingResponse
    import csv
    import io

    trades = db.get_trades_export(
        worker_id=worker_id,
        trading_mode=trading_mode,
        start_date=start_date,
        end_date=end_date,
    )

    if not trades:
        return {"message": "No trades found for the given filters.", "count": 0}

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=trades[0].keys())
    writer.writeheader()
    writer.writerows(trades)
    output.seek(0)

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=trades_export.csv"},
    )


# Servir archivos estáticos del frontend en la raíz (MUST BE LAST)
app.mount("/", StaticFiles(directory="web", html=True), name="web")
