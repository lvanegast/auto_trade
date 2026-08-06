from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
import asyncio
import os
import datetime
import hmac
from dotenv import load_dotenv
load_dotenv()
from src.database import DatabaseManager
from src.engine import TradingEngine
from src.events import SignalEvent
from src.core.security import security_guard
from src.websocket_server import ws_server, make_event
from src.telegram_bot import telegram_bot

# Inicializar Base de Datos
db = DatabaseManager()
security_guard.set_db(db)

# Inicializar Telegram Bot
from src.telegram_bot import telegram_bot
if telegram_bot.enabled:
    telegram_bot.send_alert("system", "Bot de AutoTrade iniciado en Railway")

# Inicializar FastAPI
app = FastAPI(
    title="Trading Bot API",
    description="API para el control y monitoreo del Bot de Trading",
)

_protected_mutations = {
    "/api/start",
    "/api/stop",
    "/api/order",
    "/api/order/cancel",
    "/api/position/close",
}


@app.middleware("http")
async def protect_remote_mutations(request: Request, call_next):
    """Require a bearer token for state-changing control endpoints when configured."""
    expected = os.getenv("API_AUTH_TOKEN", "")
    if expected and request.method in {"POST", "PUT", "PATCH", "DELETE"} and request.url.path in _protected_mutations:
        supplied = request.headers.get("authorization", "")
        token = supplied.removeprefix("Bearer ").strip()
        if not hmac.compare_digest(token, expected):
            return JSONResponse(status_code=401, content={"detail": "Authentication required"})
    return await call_next(request)

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


def _format_utc_iso(dt):
    if dt is None:
        return None
    if hasattr(dt, "isoformat"):
        val = dt.isoformat()
    else:
        val = str(dt)
    val = val.strip()
    if not val.endswith("Z") and "+" not in val and "-" not in val[10:]:
        val += "Z"
    return val


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


@app.get("/api/debug_tasks")
async def debug_tasks(worker_id: str = "worker_1"):
    if worker_id not in engine.workers:
        return {"error": "Worker not found"}
    worker = engine.workers[worker_id]
    
    def task_info(task):
        if task is None:
            return "None"
        info = {
            "done": task.done(),
            "cancelled": task.cancelled(),
        }
        if task.done():
            try:
                info["result"] = str(task.result())
            except Exception as e:
                info["exception"] = f"{type(e).__name__}: {e}"
        return info

    return {
        "worker_id": worker_id,
        "is_running": worker.is_running,
        "engine_task": task_info(getattr(worker, "engine_task", None)),
        "feeder_task": task_info(getattr(worker, "feeder_task", None)),
        "sync_task": task_info(getattr(worker, "sync_task", None)),
        "feeder_running": getattr(worker.feeder, "running", None) if hasattr(worker, "feeder") else None,
        "feeder_ws_running": getattr(worker.feeder._ws_manager, "_running", None) if (hasattr(worker, "feeder") and getattr(worker.feeder, "_ws_manager", None)) else None,
        "feeder_ws_task": task_info(getattr(worker.feeder._ws_manager, "_task", None)) if (hasattr(worker, "feeder") and getattr(worker.feeder, "_ws_manager", None)) else None,
        "prices_df_len": len(worker.strategy.prices_df),
    }


@app.get("/api/status")
async def get_status(worker_id: str = None):
    """Obtiene el estado actual de un worker específico, el portafolio, indicadores y precios."""
    try:
        if not worker_id:
            worker_id = "worker_1" if "worker_1" in engine.workers else (next(iter(engine.workers.keys())) if engine.workers else "worker_1")
        if worker_id not in engine.workers:
            raise HTTPException(
                status_code=404, detail=f"Worker {worker_id} no encontrado"
            )

        worker = engine.workers[worker_id]
        is_running = worker.is_running
        portfolio = db.get_portfolio(worker_id=worker_id)
        
        # Real on-chain portfolio synchronization for Limitless / EVM workers when live execution is active
        feeder_type = worker.feeder_type
        execution_type = os.getenv("EXECUTION_TYPE", "simulation").lower()
        private_key = os.getenv("LIMITLESS_PRIVATE_KEY")
        
        if feeder_type in ("limitless", "limitless_sports", "binary_arb", "maker_making") and execution_type != "simulation" and private_key:
            try:
                from web3 import Web3
                from eth_account import Account
                
                wallet_address = Account.from_key(private_key).address
                
                # Fetch live USDC balance from blockchain using Web3 with RPC fallback (EVM Base Mainnet)
                rpc_urls = [
                    'https://mainnet.base.org',
                    'https://base-mainnet.public.blastapi.io',
                    'https://rpc.ankr.com/base'
                ]
                w3 = None
                for url in rpc_urls:
                    try:
                        provider = Web3(Web3.HTTPProvider(url, request_kwargs={'timeout': 5}))
                        if provider.is_connected():
                            w3 = provider
                            break
                    except Exception:
                        pass
                
                if w3:
                    abi = [ { 'constant': True, 'inputs': [{'name': '_owner', 'type': 'address'}], 'name': 'balanceOf', 'outputs': [{'name': 'balance', 'type': 'uint256'}], 'payable': False, 'stateMutability': 'view', 'type': 'function' } ]
                    usdc_contract = w3.eth.contract(address='0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913', abi=abi)
                    usdc_balance = float(usdc_contract.functions.balanceOf(wallet_address).call() / 10**6)
                    db.update_portfolio(worker.quote_asset, usdc_balance, 0.0, worker_id=worker_id)
                    portfolio = db.get_portfolio(worker_id=worker_id)
            except Exception as pe:
                print(f"[On-Chain Sync Status Error] {pe}")

        # Formatear balance
        balances = {item["asset"]: float(item["free_balance"]) for item in portfolio}

        last_price = 0.0
        if hasattr(worker, "strategy") and worker.strategy and len(worker.strategy.prices_df) > 0:
            last_price = float(worker.strategy.prices_df.iloc[-1]["price"])
        elif getattr(worker, "last_price", 0.0) > 0:
            last_price = worker.last_price
        elif getattr(worker, "last_ask", 0.0) > 0:
            last_price = worker.last_ask
        else:
            try:
                last_trades = db.get_trades(limit=1, worker_id=worker_id)
                if last_trades:
                    last_price = float(last_trades[0]["price"])
            except Exception:
                pass

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
                    "timestamp": _format_utc_iso(row["timestamp"]),
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
                        "timestamp": _format_utc_iso(row["timestamp"]),
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

        display_symbol = worker.symbol
        if worker.feeder_type == "limitless_sports" or display_symbol == "SPORTS":
            from src.strategy.sports_arb import _sports_edge_data
            if _sports_edge_data:
                first_item = list(_sports_edge_data.values())[0]
                display_symbol = first_item.get("title", worker.symbol)
            else:
                display_symbol = worker.symbol

        return {
            "status": "ONLINE" if is_running else "OFFLINE",
            "trading_mode": db.get_state("trading_mode", "paper").upper(),
            "last_price": last_price,
            "portfolio": balances,
            "symbol": display_symbol,
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
                    "timestamp": _format_utc_iso(t["timestamp"]),
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


@app.get("/api/latency")
async def get_latency_stats(worker_id: str = None, hours: int = 24):
    """Retorna estadísticas de latencia de ejecución de órdenes (p50, p95, max por worker)."""
    try:
        stats = db.get_latency_stats(worker_id=worker_id, hours=hours)
        formatted = []
        for s in stats:
            formatted.append({
                "worker_id": s["worker_id"],
                "total_trades": s["total_trades"],
                "total": {
                    "avg_ms": float(s["avg_total_ms"]) if s["avg_total_ms"] else None,
                    "p50_ms": float(s["p50_total_ms"]) if s["p50_total_ms"] else None,
                    "p95_ms": float(s["p95_total_ms"]) if s["p95_total_ms"] else None,
                    "max_ms": float(s["max_total_ms"]) if s["max_total_ms"] else None,
                    "min_ms": float(s["min_total_ms"]) if s["min_total_ms"] else None,
                },
                "queue": {
                    "avg_ms": float(s["avg_queue_ms"]) if s["avg_queue_ms"] else None,
                    "p50_ms": float(s["p50_queue_ms"]) if s["p50_queue_ms"] else None,
                    "p95_ms": float(s["p95_queue_ms"]) if s["p95_queue_ms"] else None,
                },
                "strategy": {
                    "avg_ms": float(s["avg_strategy_ms"]) if s["avg_strategy_ms"] else None,
                    "p50_ms": float(s["p50_strategy_ms"]) if s["p50_strategy_ms"] else None,
                    "p95_ms": float(s["p95_strategy_ms"]) if s["p95_strategy_ms"] else None,
                },
                "execution": {
                    "avg_ms": float(s["avg_execution_ms"]) if s["avg_execution_ms"] else None,
                    "p50_ms": float(s["p50_execution_ms"]) if s["p50_execution_ms"] else None,
                    "p95_ms": float(s["p95_execution_ms"]) if s["p95_execution_ms"] else None,
                },
            })
        return formatted
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/latency/realtime")
async def get_realtime_latency():
    """Retorna latencia REAL medida por los feeders (API calls a orderbooks)."""
    try:
        from src.engine.latency_tracker import latency_tracker
        stats = latency_tracker.get_all_stats()
        
        # Formatear para el frontend
        result = {}
        for key, stat in stats.items():
            platform, operation = key.split(":", 1)
            if platform not in result:
                result[platform] = {}
            result[platform][operation] = {
                "count": stat["count"],
                "success_rate": round(stat["success_rate"] * 100, 1),
                "p50_ms": round(stat["p50_ms"], 1),
                "p95_ms": round(stat["p95_ms"], 1),
                "p99_ms": round(stat["p99_ms"], 1),
                "avg_ms": round(stat["avg_ms"], 1),
                "min_ms": round(stat["min_ms"], 1),
                "max_ms": round(stat["max_ms"], 1),
            }
        
        # Agregar latencia reciente por plataforma
        recent = {}
        for platform in ["limitless", "kalshi", "polymarket"]:
            recent[platform] = round(latency_tracker.get_recent_latency_ms(platform), 1)
        
        return {
            "platforms": result,
            "recent_ms": recent,
            "total_measurements": sum(s["count"] for s in stats.values()),
        }
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
                    "timestamp": _format_utc_iso(log["timestamp"]),
                    "level": log["level"],
                    "message": log["message"],
                }
            )
        return formatted_logs
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/snapshots")
async def get_snapshots(worker_id: str = None, limit: int = 100, viable_only: bool = False):
    """Retorna los últimos snapshots de oportunidades registradas por los workers."""
    try:
        snapshots = db.get_edge_snapshots(worker_id=worker_id, limit=limit, viable_only=viable_only)
        formatted = []
        for s in snapshots:
            formatted.append(
                {
                    "id": s["id"],
                    "timestamp": _format_utc_iso(s["timestamp"]) if s.get("timestamp") else None,
                    "worker_id": s.get("worker_id", "worker_2"),
                    "platform_a": s.get("platform_a"),
                    "platform_b": s.get("platform_b"),
                    "event_id": s.get("event_id"),
                    "event_title": s.get("event_title"),
                    "edge_pct": float(s.get("edge_pct") or 0.0),
                    "gross_edge_pct": float(s.get("gross_edge_pct") or 0.0),
                    "platform_a_yes_ask": float(s.get("platform_a_yes_ask") or 0.0) if s.get("platform_a_yes_ask") is not None else None,
                    "platform_b_no_ask": float(s.get("platform_b_no_ask") or 0.0) if s.get("platform_b_no_ask") is not None else None,
                    "liquidity_verified": bool(s.get("liquidity_verified")),
                    "viable": bool(s.get("viable")),
                }
            )
        return {"count": len(formatted), "snapshots": formatted}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/workers/evaluation")
async def get_workers_evaluation():
    """Retorna informe de evaluación de rendimiento y oportunidades escaneadas por cada worker."""
    try:
        evaluations = {}
        for wid, worker in engine.workers.items():
            snaps = db.get_edge_snapshots(worker_id=wid, limit=500)
            trades = db.get_trades(worker_id=wid, limit=500)
            
            total_snaps = len(snaps)
            viable_snaps = [s for s in snaps if s.get("viable")]
            avg_edge = (sum(float(s.get("edge_pct") or 0.0) for s in snaps) / total_snaps) if total_snaps > 0 else 0.0
            
            evaluations[wid] = {
                "worker_id": wid,
                "name": worker.name,
                "feeder_type": worker.feeder_type,
                "is_running": worker.is_running,
                "opportunities_scanned": total_snaps,
                "viable_opportunities": len(viable_snaps),
                "avg_edge_pct": round(avg_edge * 100, 2),
                "total_executed_trades": len(trades),
            }
        return {"workers": evaluations}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/start")
async def start_bot(request: Request, worker_id: str = None):
    """Inicia el bot de trading para un worker o para todos.
    
    GUARDRAIL: Requiere header X-Confirm-Action: true para ejecutar.
    Esto previene acciones accidentales o automáticas.
    """
    # GUARDRAIL: Verificar confirmación explícita
    confirm = request.headers.get("X-Confirm-Action", "").lower()
    if confirm != "true":
        return JSONResponse(
            status_code=400,
            content={
                "error": "Acción requiere confirmación explícita",
                "message": "Agrega header X-Confirm-Action: true para ejecutar esta acción",
                "action_requested": f"start worker {worker_id or 'all'}",
                "timestamp": datetime.datetime.now().isoformat(),
            }
        )
    
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
async def stop_bot(request: Request, worker_id: str = None):
    """Detiene el bot de trading para un worker o para todos.
    
    GUARDRAIL: Requiere header X-Confirm-Action: true para ejecutar.
    Esto previene acciones accidentales o automáticas.
    
    ACCIONES AUTOMÁTICAS:
    - Cancela todas las órdenes pendientes en Limitless
    - Reporta posiciones abiertas (NO las cierra automáticamente)
    
    ACCIONES QUE REQUIEREN CONFIRMACIÓN:
    - Cerrar posiciones abiertas (decisión con impacto en P&L)
    """
    # GUARDRAIL: Verificar confirmación explícita
    confirm = request.headers.get("X-Confirm-Action", "").lower()
    if confirm != "true":
        return JSONResponse(
            status_code=400,
            content={
                "error": "Acción requiere confirmación explícita",
                "message": "Agrega header X-Confirm-Action: true para ejecutar esta acción",
                "action_requested": f"stop worker {worker_id or 'all'}",
                "timestamp": datetime.datetime.now().isoformat(),
            }
        )
    
    if worker_id:
        if worker_id not in engine.workers:
            raise HTTPException(
                status_code=404, detail=f"Worker {worker_id} no encontrado"
            )
        worker = engine.workers[worker_id]
        if not worker.is_running:
            return {"message": f"El worker {worker_id} ya está apagado."}
        result = await engine.stop(worker_id)
        return {
            "message": f"Worker {worker_id} detenido exitosamente.",
            "orders_cancelled": result.get("orders_cancelled", 0),
            "open_positions": result.get("open_positions", 0),
            "open_positions_details": result.get("open_positions_details", []),
        }
    else:
        result = await engine.stop()
        return {
            "message": "Todos los workers detenidos exitosamente.",
            "orders_cancelled": result.get("orders_cancelled", 0),
            "open_positions": result.get("open_positions", 0),
            "open_positions_details": result.get("open_positions_details", []),
        }


@app.post("/api/order")
async def place_manual_order(request: Request, body: dict):
    """Envía una orden de compra o venta manual para un worker.
    
    GUARDRAIL: Requiere header X-Confirm-Action: true para ejecutar.
    Esto previene acciones accidentales o automáticas.
    """
    # GUARDRAIL: Verificar confirmación explícita
    confirm = request.headers.get("X-Confirm-Action", "").lower()
    if confirm != "true":
        return JSONResponse(
            status_code=400,
            content={
                "error": "Acción requiere confirmación explícita",
                "message": "Agrega header X-Confirm-Action: true para ejecutar esta acción",
                "action_requested": f"place order for worker {body.get('worker_id', 'worker_1')}",
                "timestamp": datetime.datetime.now().isoformat(),
            }
        )
    
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
            close_price = p.get("exit_price") if p.get("exit_price") is not None else p.get("close_price")
            close_time = p.get("exit_time") if p.get("exit_time") is not None else p.get("close_time")
            close_reason = p.get("exit_reason") if p.get("exit_reason") is not None else p.get("close_reason")
            formatted.append(
                {
                    "id": p["id"],
                    "worker_id": p["worker_id"],
                    "symbol": p["symbol"],
                    "side": p["side"],
                    "entry_price": float(p["entry_price"]),
                    "entry_lead_price": float(p["entry_lead_price"])
                    if p.get("entry_lead_price") is not None
                    else None,
                    "amount": float(p["amount"])
                    if p.get("amount") is not None
                    else None,
                    "entry_time": _format_utc_iso(entry_time),
                    "status": p["status"],
                    "close_price": float(close_price)
                    if close_price is not None
                    else None,
                    "close_time": _format_utc_iso(close_time),
                    "close_reason": close_reason,
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
    from src.strategy.sports_arb import _sports_edge_data

    pairs = get_active_pairs()
    all_opportunities = cross_platform_tracker.scan_all_pairs(min_edge_pct=0.01)

    results = []
    for opp in all_opportunities:
        pair = next((p for p in pairs if p["event_id"] == opp["event_id"]), None)
        if pair:
            opp["event_label"] = pair["event_label"]
            opp["category"] = pair["category"]
        results.append(opp)

    price_map = {}
    for pair in pairs:
        both = cross_platform_tracker.get_both_books(pair["event_id"])
        kalshi_book = both.get("kalshi") or {}
        limitless_book = both.get("limitless") or {}
        price_map[pair["event_id"]] = {
            "event_label": pair["event_label"],
            "category": pair["category"],
            "kalshi": {
                "price": kalshi_book.get("yes_ask", 0.0),
                "bid": kalshi_book.get("yes_bid", 0.0),
                "ask": kalshi_book.get("yes_ask", 0.0),
            },
            "limitless": {
                "price": limitless_book.get("yes_ask", 0.0),
                "bid": limitless_book.get("yes_bid", 0.0),
                "ask": limitless_book.get("yes_ask", 0.0),
            },
        }

    for event_id, edge_info in _sports_edge_data.items():
        total_yes = edge_info.get("total_yes", 0.95)
        edge_val = edge_info.get("edge", 0.05)
        title = edge_info.get("title", event_id)

        if event_id not in price_map:
            price_map[event_id] = {
                "event_label": f"{title}",
                "category": "sports",
                "kalshi": {"price": round(total_yes * 0.5, 4), "bid": round(total_yes * 0.49, 4), "ask": round(total_yes * 0.5, 4)},
                "limitless": {"price": round(1.0 - edge_val, 4), "bid": round(0.95 - edge_val, 4), "ask": round(1.0 - edge_val, 4)},
            }

        results.append({
            "event_id": event_id,
            "event_label": f"{title}",
            "direction": "BUY_ALL_YES_1XN" if edge_val > 0 else "BUY_ALL_NO_1XN",
            "kalshi_yes": round(total_yes * 0.5, 4),
            "polymarket_yes": round(1.0 - total_yes, 4),
            "edge_pct": abs(edge_val),
            "total_cost": total_yes,
            "guaranteed_profit": abs(edge_val),
            "outcomes": edge_info.get("outcomes", []),
        })

    return {"opportunities": results, "price_map": price_map, "catalog_version": "2.0.0"}


@app.get("/api/opportunities")
async def get_opportunities():
    """Dashboard de oportunidades: arbitraje 2 piernas + 1xN, con profundidad y exposición."""
    from src.strategy.cross_platform_tracker import cross_platform_tracker
    from src.strategy.market_pairs import get_active_pairs, CATALOG_VERSION
    from src.strategy.sports_arb import _sports_edge_data
    from src.engine.friction_guard import friction_guard

    pairs = get_active_pairs()
    all_opportunities = cross_platform_tracker.scan_all_pairs(min_edge_pct=0.01)

    enriched = []
    for opp in all_opportunities:
        pair = next((p for p in pairs if p["event_id"] == opp["event_id"]), None)
        if pair:
            opp["event_label"] = pair["event_label"]
            opp["category"] = pair["category"]
            opp["expiration"] = pair.get("expiration")
            opp["resolution"] = pair.get("resolution", {})

        is_profitable, net_edge, _, friction_details = friction_guard.validate_arbitrage_profitability(
            leg1_feeder=opp["buy_platform"],
            leg2_feeder=opp["hedge_platform"],
            gross_edge_pct=opp["edge_pct"],
            position_size_usd=50.0,
        )
        opp["net_edge_pct"] = net_edge
        opp["friction_total"] = friction_details.get("total_friction", 0.0)
        opp["is_profitable"] = is_profitable
        opp["friction_details"] = friction_details
        enriched.append(opp)

    for event_id, edge_info in _sports_edge_data.items():
        total_yes = edge_info.get("total_yes", 0.95)
        edge_val = edge_info.get("edge", 0.05)
        title = edge_info.get("title", event_id)
        outcomes = edge_info.get("outcomes", [])

        enriched.append({
            "event_id": event_id,
            "event_label": title,
            "category": "sports",
            "direction": "BUY_ALL_YES_1XN" if edge_val > 0 else "BUY_ALL_NO_1XN",
            "edge_pct": abs(edge_val),
            "total_cost": total_yes,
            "guaranteed_profit": abs(edge_val),
            "is_profitable": abs(edge_val) > 0.02,
            "outcomes": outcomes,
            "num_outcomes": len(outcomes),
        })

    return {
        "catalog_version": CATALOG_VERSION,
        "total_opportunities": len(enriched),
        "profitable_count": sum(1 for o in enriched if o.get("is_profitable")),
        "opportunities": enriched,
    }

@app.post("/api/backtest")
async def run_backtest_endpoint(worker_id: str = "worker_3", days: int = 7, initial_capital: float = 1000.0):
    """Ejecuta una simulación de backtesting histórica con DATOS REALES de mercado para probar la rentabilidad."""
    if worker_id not in engine.workers:
        raise HTTPException(status_code=404, detail=f"Worker {worker_id} no encontrado")

    worker = engine.workers[worker_id]
    from src.engine.backtester import BacktestEngine
    import pandas as pd
    import urllib.request
    import json
    import datetime as dt_mod

    bars_count = min(1000, days * 24 * 60)
    dates = []
    prices = []
    data_source = "Binance Public REST API (Datos Reales)"

    try:
        # Si el worker opera Crypto / Spot (Worker 1, Worker 4, Hyperliquid, dYdX) -> Descargar velas reales de Binance
        if worker.feeder_type in ["binance", "hyperliquid", "dydx", "alpaca"] or "BTC" in worker.symbol:
            url = f"https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=1m&limit={bars_count}"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                if resp.status == 200:
                    raw_data = json.loads(resp.read().decode("utf-8"))
                    for bar in raw_data:
                        # bar[0] = open_time_ms, bar[4] = close_price
                        open_time = dt_mod.datetime.fromtimestamp(bar[0] / 1000.0)
                        close_price = float(bar[4])
                        dates.append(open_time)
                        prices.append(close_price)
        else:
            # Conexión 100% REAL usando el SDK Oficial de Limitless Exchange
            data_source = "Limitless Exchange Official SDK (Datos Reales de Mercado)"
            from limitless_sdk.api import HttpClient
            from limitless_sdk.markets import MarketFetcher
            
            http_client = HttpClient()
            kalshi_prices = []
            limitless_prices = []
            try:
                market_fetcher = MarketFetcher(http_client)
                market_group = await market_fetcher.get_market("core-pce-yoy-june-2026-1784042260443")
                submarkets = getattr(market_group, "markets", [])
                now = dt_mod.datetime.now()
                idx = 0
                for sub in submarkets:
                    sub_detail = await market_fetcher.get_market(sub.slug)
                    sub_prices = getattr(sub_detail, "prices", None)
                    if sub_prices and len(sub_prices) >= 2:
                        p1 = float(sub_prices[0]) # YES Real
                        p2 = float(sub_prices[1]) # NO Real
                        dates.append(now - dt_mod.timedelta(minutes=idx * 2))
                        prices.append(p1)
                        kalshi_prices.append(p1)
                        limitless_prices.append(p2)
                        idx += 1
            finally:
                await http_client.close()

            if not prices:
                raise ValueError("No se pudieron obtener mercados activos de Limitless SDK")

    except Exception as e_fetch:
        # Fallback de seguridad en caso de timeout
        data_source = f"Fallback Local ({e_fetch})"
        now = dt_mod.datetime.now()
        dates = [now - dt_mod.timedelta(minutes=i) for i in range(bars_count, 0, -1)]
        prices = [0.48 for _ in range(bars_count)]
        kalshi_prices = [0.48 for _ in range(bars_count)]
        limitless_prices = [0.48 for _ in range(bars_count)]

    df_dict = {
        "timestamp": dates,
        "price": prices,
        "bid": [p * 0.9995 for p in prices],
        "ask": [p * 1.0005 for p in prices]
    }
    if kalshi_prices and limitless_prices:
        df_dict["kalshi_price"] = kalshi_prices
        df_dict["limitless_price"] = limitless_prices

    df_history = pd.DataFrame(df_dict)

    backtester = BacktestEngine(initial_capital=initial_capital, position_size_usd=50.0)
    results = backtester.run_backtest(worker.strategy, df_history)

    return {
        "worker_id": worker_id,
        "strategy": worker.strategy.__class__.__name__,
        "days_simulated": days,
        "data_source": data_source,
        "candles_analyzed": len(df_history),
        "metrics": results
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


@app.post("/api/circuit-breaker/reset")
async def reset_circuit_breaker():
    """Reset the circuit breaker after daily loss halt."""
    from src.engine.circuit_breaker import circuit_breaker
    circuit_breaker.reset_circuit()
    current_equity = db.get_total_equity_usd()
    circuit_breaker.starting_capital_day = current_equity
    db.log("INFO", f"Circuit breaker reset. Capital inicial: ${current_equity:.2f}", "ALL")
    return {
        "status": "RESET",
        "message": f"Circuit breaker reset. Capital inicial: ${current_equity:.2f}",
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


# ==================== TELEGRAM COMMANDS ====================

@app.get("/api/telegram/status")
async def telegram_status():
    """Send worker status to Telegram."""
    if not telegram_bot.enabled:
        return {"error": "Telegram bot not configured"}
    
    workers = []
    for wid, worker in engine.workers.items():
        workers.append({
            "name": worker.name,
            "is_running": worker.is_running,
            "symbol": worker.symbol,
        })
    
    telegram_bot.send_worker_status(workers)
    return {"status": "sent", "workers": len(workers)}


@app.get("/api/telegram/balance")
async def telegram_balance():
    """Send balance to Telegram."""
    if not telegram_bot.enabled:
        return {"error": "Telegram bot not configured"}
    
    # For now, send placeholder
    telegram_bot.send_balance({"limitless": 0, "kalshi": 0, "total": 0})
    return {"status": "sent"}


@app.get("/api/telegram/positions")
async def telegram_positions():
    """Send open positions to Telegram."""
    if not telegram_bot.enabled:
        return {"error": "Telegram bot not configured"}
    
    positions = db.get_open_positions(worker_id=None)
    telegram_bot.send_positions(positions)
    return {"status": "sent", "positions": len(positions)}


@app.get("/api/telegram/report")
async def telegram_report():
    """Send daily report to Telegram."""
    if not telegram_bot.enabled:
        return {"error": "Telegram bot not configured"}
    
    # Get stats from database
    stats = {
        "opportunities": 0,
        "trades": 0,
        "pnl": 0,
        "avg_edge": 0,
        "active_workers": sum(1 for w in engine.workers.values() if w.is_running),
        "total_workers": len(engine.workers),
        "errors": 0,
    }
    
    telegram_bot.send_daily_report(stats)
    return {"status": "sent"}


@app.get("/api/telegram/test")
async def telegram_test():
    """Send test message to Telegram."""
    if not telegram_bot.enabled:
        return {"error": "Telegram bot not configured"}
    
    result = telegram_bot.send_alert("info", "Test message from AutoTrade bot")
    return {"status": "sent" if result else "failed"}


@app.get("/api/opportunities/tracking")
async def get_opportunity_tracking():
    """Get all tracked opportunities with their resolution status."""
    opportunities = db.get_pending_opportunities()
    return {
        "pending": len(opportunities),
        "opportunities": [
            {
                "id": o[0],
                "event_id": o[1],
                "event_title": o[2],
                "edge_pct": o[3],
                "entry_price": o[4],
                "timestamp": str(o[6]) if o[6] else None,
            }
            for o in opportunities
        ]
    }


@app.post("/api/opportunities/{opp_id}/resolve")
async def resolve_opportunity(opp_id: int, resolution: str, actual_profit: float = 0.0):
    """Mark an opportunity as resolved (won/lost) with actual profit."""
    db.update_opportunity_resolution(opp_id, resolution, actual_profit)
    return {"status": "resolved", "id": opp_id, "resolution": resolution, "profit": actual_profit}


# Servir archivos estáticos del frontend en la raíz (MUST BE LAST)
if os.path.exists("web"):
    app.mount("/", StaticFiles(directory="web", html=True), name="web")
elif os.path.exists("frontend/dist"):
    app.mount("/", StaticFiles(directory="frontend/dist", html=True), name="frontend")
