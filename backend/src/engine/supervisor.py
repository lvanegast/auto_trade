import asyncio
import os
import requests
import uuid
import datetime
from src.database import DatabaseManager
from src.events import SignalEvent
from src.strategy.lead_lag_arbitrage import LeadLagArbitrageStrategy
from src.strategy.cross_platform_arb import CrossPlatformArbitrageStrategy
from src.feeders.mock_feeder import MockFeeder
from src.feeders.oanda_feeder import OandaFeeder
from src.feeders.ig_feeder import IGFeeder
from src.feeders.alpaca_feeder import AlpacaFeeder
from src.feeders.kalshi_feeder import KalshiFeeder
from src.feeders.binance_feeder import BinanceFeeder
from src.feeders.polymarket_feeder import PolymarketFeeder
from src.feeders.limitless_feeder import LimitlessFeeder
from src.feeders.limitless_sports_feeder import LimitlessSportsFeeder
from src.feeders.binary_arb_feeder import LimitlessOracleFeeder
from src.strategy.sports_arb import SportsArbitrageStrategy
from src.strategy.binary_arb_strategy import OracleMomentumStrategy
from src.core.security import security_guard
from src.websocket_server import ws_server, make_event


class TradingWorker:
    def __init__(
        self,
        worker_id: str,
        name: str,
        symbol: str,
        feeder_type: str,
        db: DatabaseManager,
    ):
        self.worker_id = worker_id
        self.name = name
        self.symbol = symbol.upper()
        self.feeder_type = feeder_type.lower()
        self.db = db
        self.queue = asyncio.Queue()

        self.base_asset, self.quote_asset = self._parse_symbol()

        # Inicializar estrategia según tipo de feeder
        if self.feeder_type in ("kalshi", "polymarket", "limitless"):
            min_edge = float(os.getenv("MIN_ARB_EDGE_PCT", "0.03"))
            position_size = float(os.getenv("ARB_POSITION_SIZE_PCT", "0.5"))
            self.strategy = CrossPlatformArbitrageStrategy(
                self.symbol,
                feeder_type=self.feeder_type,
                min_edge_pct=min_edge,
                position_size_pct=position_size,
                db=self.db,
                worker_id=self.worker_id,
            )
        elif self.feeder_type == "limitless_sports":
            min_edge = float(os.getenv("SPORTS_ARB_EDGE_PCT", "0.03"))
            position_size_usd = float(os.getenv("SPORTS_POSITION_SIZE_USD", "10.0"))
            self.strategy = SportsArbitrageStrategy(
                self.symbol,
                feeder_type=self.feeder_type,
                min_edge_pct=min_edge,
                position_size_usd=position_size_usd,
                db=self.db,
                worker_id=self.worker_id,
            )
        elif self.feeder_type == "binary_arb":
            self.strategy = OracleMomentumStrategy(
                self.symbol,
                db=self.db,
                worker_id=self.worker_id,
            )
        else:
            self.strategy = LeadLagArbitrageStrategy(
                self.symbol, db=self.db, worker_id=self.worker_id
            )

        if self.feeder_type == "oanda":
            self.feeder = OandaFeeder(self.symbol, self.queue)
        elif self.feeder_type == "ig":
            self.feeder = IGFeeder(self.symbol, self.queue)
        elif self.feeder_type == "alpaca":
            self.feeder = AlpacaFeeder(self.symbol, self.queue)
        elif self.feeder_type == "kalshi":
            self.feeder = KalshiFeeder(self.symbol, self.queue)
        elif self.feeder_type == "binance":
            self.feeder = BinanceFeeder(self.symbol, self.queue)
        elif self.feeder_type == "polymarket":
            self.feeder = PolymarketFeeder(self.symbol, self.queue)
        elif self.feeder_type == "limitless":
            self.feeder = LimitlessFeeder(self.symbol, self.queue)
        elif self.feeder_type == "limitless_sports":
            self.feeder = LimitlessSportsFeeder(self.symbol, self.queue)
        elif self.feeder_type == "binary_arb":
            self.feeder = LimitlessOracleFeeder(self.symbol, self.queue)
        else:
            self.feeder = MockFeeder(self.symbol, self.queue, interval=1.0)

        self.is_running = False
        self.engine_task = None
        self.feeder_task = None
        self.sync_task = None
        self.last_bid = 0.0
        self.last_ask = 0.0
        self.trading_mode = os.getenv("ALPACA_TRADING_MODE", "paper").lower()

        # Cliente de ejecución para Alpaca
        self.alpaca_client = None
        self.execution_type = os.getenv("EXECUTION_TYPE", "alpaca").lower()
        if self.feeder_type == "alpaca" and self.execution_type == "alpaca":
            from alpaca.trading.client import TradingClient

            api_key = os.getenv("ALPACA_API_KEY")
            secret_key = os.getenv("ALPACA_SECRET_KEY")
            trading_mode = os.getenv("ALPACA_TRADING_MODE", "paper").lower()
            is_paper = trading_mode == "paper"

            if api_key and secret_key and "your_alpaca" not in api_key:
                self.alpaca_client = TradingClient(api_key, secret_key, paper=is_paper)
                self.db.log(
                    "INFO",
                    f"Cliente de ejecución de Alpaca inicializado (Modo: {trading_mode.upper()}).",
                    self.worker_id,
                )
            else:
                self.db.log(
                    "WARNING",
                    "Cliente de ejecución de Alpaca no configurado debido a credenciales faltantes o por defecto.",
                    self.worker_id,
                )

        # Credenciales de OANDA
        self.oanda_account_id = os.getenv("OANDA_ACCOUNT_ID")
        self.oanda_token = os.getenv("OANDA_API_TOKEN")
        self.oanda_env = os.getenv("OANDA_ENV", "practice").lower()
        if self.oanda_env == "trade":
            self.oanda_rest_url = (
                f"https://api-fxtrade.oanda.com/v3/accounts/{self.oanda_account_id}"
            )
        else:
            self.oanda_rest_url = (
                f"https://api-fxpractice.oanda.com/v3/accounts/{self.oanda_account_id}"
            )

        # Credenciales de Kalshi
        self.kalshi_api_key_id = os.getenv("KALSHI_API_KEY_ID")
        self.kalshi_private_key_path = os.getenv("KALSHI_PRIVATE_KEY_PATH")
        self.kalshi_env = os.getenv("KALSHI_ENV", "demo").lower()
        if self.kalshi_env == "prod":
            self.kalshi_rest_url = "https://trading-api.kalshi.com/trade-api/v2"
        else:
            self.kalshi_rest_url = "https://demo-api.kalshi.co/trade-api/v2"

        # Saldo virtual inicial
        self._init_portfolio()

    def _parse_symbol(self) -> tuple:
        symbol = self.symbol
        if symbol.isdigit() or self.feeder_type in (
            "polymarket",
            "limitless",
            "limitless_sports",
            "binary_arb",
        ):
            return symbol, "USD"

        if "EURUSD" in symbol:
            return "EUR", "USD"
        elif "GBPUSD" in symbol:
            return "GBP", "USD"

        if "_" in symbol:
            parts = symbol.split("_")
            return parts[0], parts[1]

        if "/" in symbol:
            parts = symbol.split("/")
            return parts[0], parts[1]

        if symbol.startswith("BTC"):
            return "BTC", "USD" if self.feeder_type == "alpaca" else "USDT"
        elif symbol.startswith("EUR"):
            return "EUR", "USD"
        elif symbol.startswith("GBP"):
            return "GBP", "USD"

        # Para Kalshi (ej. INFLATION-26 o FED-26)
        if "-" in symbol:
            parts = symbol.split("-")
            return parts[0], "USD"

        mid = len(symbol) // 2
        return symbol[:mid], symbol[mid:]

    def _update_db_portfolio(
        self, asset: str, free_balance: float, locked_balance: float = 0.0
    ):
        self.db.update_portfolio(
            asset, free_balance, locked_balance, worker_id=self.worker_id
        )

    def _init_portfolio(self):
        # Si usamos cuentas reales/demo conectadas con APIs, la sincronización se hace al iniciar (start)
        if self.alpaca_client and self.feeder_type == "alpaca":
            return
        if self.feeder_type == "oanda" and self.oanda_account_id and self.oanda_token:
            return
        if (
            self.feeder_type == "kalshi"
            and self.kalshi_api_key_id
            and self.kalshi_private_key_path
        ):
            return
        if self.feeder_type in ("limitless", "limitless_sports"):
            return

        portfolio = self.db.get_portfolio(self.worker_id)
        assets = [item["asset"] for item in portfolio]

        if self.quote_asset not in assets:
            self._update_db_portfolio(self.quote_asset, 10000.0)
            self.db.log(
                "INFO",
                f"Portafolio inicializado con 10,000 {self.quote_asset} para simulación.",
                self.worker_id,
            )
        if self.base_asset not in assets:
            self._update_db_portfolio(self.base_asset, 0.0)

    def _restore_position_from_db(self):
        """Restaura el estado de la posición abierta desde la DB al iniciar el worker."""
        pos = self.db.get_open_position_by_worker(self.worker_id)
        if pos:
            self.strategy.last_position = pos["side"]
            self.strategy.entry_price = float(pos["entry_price"])
            if hasattr(self.strategy, "entry_lead_price"):
                self.strategy.entry_lead_price = float(pos["entry_lead_price"])
            self.strategy._position_id = pos["id"]
            from datetime import timezone

            entry_time = pos["entry_time"]
            if entry_time.tzinfo is None:
                entry_time = entry_time.replace(tzinfo=timezone.utc)
            now = datetime.datetime.now(timezone.utc)
            if now.tzinfo is None:
                now = now.replace(tzinfo=timezone.utc)
            elapsed = (now - entry_time).total_seconds()
            self.strategy.entry_time = asyncio.get_event_loop().time() - elapsed
            self.db.log(
                "INFO",
                f"Posición restaurada desde DB: {pos['side']} @ {pos['entry_price']} (ID: {pos['id']})",
                self.worker_id,
            )

    async def start(self):
        if self.is_running:
            return

        self.is_running = True
        self._init_portfolio()
        self.db.log(
            "INFO",
            f"Iniciando Worker '{self.name}' ({self.feeder_type.upper()}) para {self.symbol}...",
            self.worker_id,
        )

        # Restaurar posición abierta desde DB si existe
        self._restore_position_from_db()

        # Sincronizar balances reales según corresponda
        try:
            if self.alpaca_client and self.feeder_type == "alpaca":
                await self._sync_alpaca_portfolio()
            elif (
                self.feeder_type == "oanda"
                and self.oanda_account_id
                and self.oanda_token
            ):
                await self._sync_oanda_portfolio()
            elif (
                self.feeder_type == "kalshi"
                and self.kalshi_api_key_id
                and self.kalshi_private_key_path
            ):
                await self._sync_kalshi_portfolio()
        except Exception as e:
            self.db.log(
                "WARNING",
                f"No se pudo sincronizar el portafolio real ({e}). Continuando en modo de simulación.",
                self.worker_id,
            )

        # Pre-cargar historial para evitar arranque en frío
        await self._warm_up_strategy()

        self.engine_task = asyncio.create_task(self._event_loop())
        self.feeder_task = asyncio.create_task(self.feeder.start())
        self.sync_task = asyncio.create_task(self._periodic_sync())

        # Notificar a clientes WebSocket del cambio de estado
        await ws_server.broadcast(
            self.worker_id,
            make_event(
                "worker_status",
                {
                    "worker_id": self.worker_id,
                    "is_running": True,
                    "symbol": self.symbol,
                    "feeder_type": self.feeder_type,
                    "name": self.name,
                },
            ),
        )

    async def stop(self):
        if not self.is_running:
            return

        self.is_running = False
        self.db.log("INFO", f"Deteniendo Worker '{self.name}'...", self.worker_id)

        # Notificar a clientes WebSocket del cambio de estado
        await ws_server.broadcast(
            self.worker_id,
            make_event(
                "worker_status",
                {
                    "worker_id": self.worker_id,
                    "is_running": False,
                    "symbol": self.symbol,
                    "feeder_type": self.feeder_type,
                    "name": self.name,
                },
            ),
        )

        await self.feeder.stop()

        if self.feeder_task:
            self.feeder_task.cancel()
        if self.engine_task:
            self.engine_task.cancel()
        if self.sync_task:
            self.sync_task.cancel()

        self.feeder_task = None
        self.engine_task = None
        self.sync_task = None

    async def _periodic_sync(self):
        print(f"[Worker {self.worker_id}] Tarea de sincronización periódica iniciada.")
        try:
            while self.is_running:
                await asyncio.sleep(10)
                if not self.is_running:
                    break
                try:
                    if self.alpaca_client:
                        await self._sync_alpaca_portfolio()
                    elif (
                        self.feeder_type == "oanda"
                        and self.oanda_account_id
                        and self.oanda_token
                    ):
                        await self._sync_oanda_portfolio()
                    elif (
                        self.feeder_type == "kalshi"
                        and self.kalshi_api_key_id
                        and self.kalshi_private_key_path
                    ):
                        await self._sync_kalshi_portfolio()
                    elif self.feeder_type in ("limitless", "limitless_sports"):
                        pass  # Limitless: on-chain, no sync needed in simulation
                except Exception as e:
                    print(f"[Sync Error] Error en sincronización periódica: {e}")

                # Update security guard with total equity across ALL workers for drawdown tracking
                try:
                    total = self.db.get_total_equity_usd()
                    security_guard.update_equity(total)
                except Exception:
                    pass
        except asyncio.CancelledError:
            print(
                f"[Worker {self.worker_id}] Tarea de sincronización periódica cancelada."
            )

    async def _event_loop(self):
        print(f"[Worker {self.worker_id}] Loop de eventos iniciado para {self.symbol}.")
        try:
            while self.is_running:
                event = await self.queue.get()
                try:
                    if event.event_type == "PRICE_UPDATE":
                        self.last_bid = event.bid
                        self.last_ask = event.ask
                        signal = self.strategy.on_price_update(event)
                        # Broadcast del precio a clientes WebSocket (no bloqueante)
                        if ws_server.has_clients(self.worker_id):
                            await ws_server.broadcast(
                                self.worker_id,
                                make_event(
                                    "price_update",
                                    {
                                        "symbol": event.symbol,
                                        "price": event.price,
                                        "bid": event.bid,
                                        "ask": event.ask,
                                        "teorical_probability": getattr(
                                            self.strategy, "teorical_probability", 0.0
                                        ),
                                        "edge": getattr(self.strategy, "edge", 0.0),
                                        "last_position": getattr(
                                            self.strategy, "last_position", None
                                        ),
                                        "entry_price": getattr(
                                            self.strategy, "entry_price", 0.0
                                        ),
                                        "position_id": getattr(
                                            self.strategy, "_position_id", None
                                        ),
                                        "arbitrage_opportunity": getattr(
                                            self.strategy,
                                            "last_arbitrage_opportunity",
                                            None,
                                        ),
                                    },
                                ),
                            )
                        if signal:
                            # Execute this signal immediately
                            await self._execute_order(signal)
                            if ws_server.has_clients(self.worker_id):
                                await ws_server.broadcast(
                                    self.worker_id,
                                    make_event(
                                        "trade_update",
                                        {
                                            "symbol": signal.symbol,
                                            "side": signal.side,
                                            "price": signal.price,
                                            "reason": signal.reason,
                                        },
                                    ),
                                )
                            # Batch: execute all pending 1×N signals in same tick
                            pending = getattr(self.strategy, "_pending_signals", [])
                            while pending:
                                next_signal = pending.pop(0)
                                await self._execute_order(next_signal)
                                if ws_server.has_clients(self.worker_id):
                                    await ws_server.broadcast(
                                        self.worker_id,
                                        make_event(
                                            "trade_update",
                                            {
                                                "symbol": next_signal.symbol,
                                                "side": next_signal.side,
                                                "price": next_signal.price,
                                                "reason": next_signal.reason,
                                            },
                                        ),
                                    )
                except Exception as e:
                    self.db.log("ERROR", f"Error en event_loop: {e}", self.worker_id)
                finally:
                    self.queue.task_done()
        except asyncio.CancelledError:
            print(f"[Worker {self.worker_id}] Loop de eventos cancelado.")

    async def _execute_order(self, signal: SignalEvent):
        self.db.log("INFO", f"Procesando señal: {signal}", self.worker_id)

        # SecurityGuard: pre-trade check (skip for SELL — closing positions should never be blocked)
        if signal.side != "SELL":
            can_trade, reason = security_guard.can_trade(self.worker_id)
            if not can_trade:
                self.db.log(
                    "WARNING",
                    f"[SecurityGuard] Orden RECHAZADA: {reason}",
                    self.worker_id,
                )
                return

            security_guard.record_trade()

        # Cargar balances actuales de la base de datos para este worker
        balances = {
            item["asset"]: float(item["free_balance"])
            for item in self.db.get_portfolio(self.worker_id)
        }
        quote_balance = balances.get(self.quote_asset, 0.0)
        base_balance = balances.get(self.base_asset, 0.0)

        price = signal.price

        # Determinar cantidad a operar: priorizar signal.amount, fallback a 50% del balance
        # Si signal.amount está entre 0 y 1 (exclusivo), se interpreta como % del balance
        if getattr(signal, "amount", None) is not None:
            if 0 < signal.amount < 1:
                pct = signal.amount
                requested_amount = None
                requested_pct = pct
            else:
                requested_amount = signal.amount
                requested_pct = None
        else:
            requested_amount = None
            requested_pct = None

        # 1. EJECUCIÓN CON ALPACA (Acciones / Criptomonedas)
        if self.alpaca_client and self.feeder_type == "alpaca":
            from alpaca.trading.requests import MarketOrderRequest
            from alpaca.trading.enums import OrderSide, TimeInForce

            try:
                if signal.side == "BUY":
                    if requested_pct is not None:
                        spend_amount = quote_balance * requested_pct
                        amount_to_buy = spend_amount / price
                    elif requested_amount is not None:
                        spend_amount = requested_amount * price
                        amount_to_buy = requested_amount
                    else:
                        spend_amount = quote_balance * 0.5
                        amount_to_buy = spend_amount / price

                    is_crypto_symbol = "/" in self.feeder.symbol
                    qty = (
                        round(amount_to_buy, 6)
                        if is_crypto_symbol
                        else round(amount_to_buy, 4)
                    )

                    if qty <= 0:
                        self.db.log(
                            "WARNING",
                            "Cantidad a comprar es 0 o insuficiente. Abortando orden.",
                            self.worker_id,
                        )
                        return

                    order_data = MarketOrderRequest(
                        symbol=self.feeder.symbol.replace("/", ""),
                        qty=qty,
                        side=OrderSide.BUY,
                        time_in_force=TimeInForce.GTC,
                    )
                else:
                    if requested_pct is not None:
                        amount_to_sell = base_balance * requested_pct
                    elif requested_amount is not None:
                        amount_to_sell = requested_amount
                    else:
                        amount_to_sell = base_balance

                    is_crypto_symbol = "/" in self.feeder.symbol
                    qty = (
                        round(amount_to_sell, 6)
                        if is_crypto_symbol
                        else round(amount_to_sell, 4)
                    )

                    if qty <= 0:
                        self.db.log(
                            "WARNING",
                            "Cantidad a vender es 0 o insuficiente. Abortando orden.",
                            self.worker_id,
                        )
                        return

                    order_data = MarketOrderRequest(
                        symbol=self.feeder.symbol.replace("/", ""),
                        qty=qty,
                        side=OrderSide.SELL,
                        time_in_force=TimeInForce.GTC,
                    )

                self.db.log(
                    "INFO",
                    f"Enviando orden a Alpaca: {order_data.side} {order_data.qty} {order_data.symbol}",
                    self.worker_id,
                )
                order = await asyncio.to_thread(
                    self.alpaca_client.submit_order, order_data=order_data
                )

                order_status = (
                    str(order.status.value).upper()
                    if hasattr(order.status, "value")
                    else str(order.status).upper()
                )
                self.db.save_trade(
                    symbol=self.symbol,
                    side=signal.side,
                    price=price,
                    amount=float(order.qty),
                    external_order_id=str(order.id),
                    status=order_status,
                    worker_id=self.worker_id,
                    position_id=getattr(signal, "position_id", None),
                    trading_mode=self.trading_mode,
                )
                await self._sync_alpaca_portfolio()
            except Exception as e:
                self.db.log(
                    "ERROR", f"Fallo al enviar orden a Alpaca: {e}", self.worker_id
                )
            return

        # 2. EJECUCIÓN CON OANDA (Forex)
        if self.feeder_type == "oanda" and self.oanda_account_id and self.oanda_token:
            try:
                if requested_pct is not None:
                    units = int(quote_balance * requested_pct)
                elif requested_amount is not None:
                    units = int(requested_amount)
                else:
                    units = int(quote_balance * 0.5)
                if units <= 0:
                    units = 1000
                if signal.side == "SELL":
                    units = -units

                url = f"{self.oanda_rest_url}/orders"
                headers = {
                    "Authorization": f"Bearer {self.oanda_token}",
                    "Content-Type": "application/json",
                }
                data = {
                    "order": {
                        "instrument": self.feeder.symbol,
                        "units": str(units),
                        "type": "MARKET",
                        "timeInForce": "FOK",
                        "positionFill": "DEFAULT",
                    }
                }

                self.db.log(
                    "INFO",
                    f"Enviando orden a OANDA: {signal.side} {abs(units)} unidades",
                    self.worker_id,
                )
                response = await asyncio.to_thread(
                    requests.post, url, headers=headers, json=data
                )

                if response.status_code in [200, 201]:
                    res_data = response.json()
                    order_fill = res_data.get("orderFillTransaction", {})
                    trade_id = order_fill.get("id", "N/A")

                    self.db.save_trade(
                        symbol=self.symbol,
                        side=signal.side,
                        price=price,
                        amount=float(abs(units)),
                        external_order_id=str(trade_id),
                        status="COMPLETED",
                        worker_id=self.worker_id,
                        position_id=getattr(signal, "position_id", None),
                        trading_mode=self.trading_mode,
                    )
                    await self._sync_oanda_portfolio()
                else:
                    self.db.log(
                        "ERROR",
                        f"Fallo en orden OANDA. Status: {response.status_code}",
                        self.worker_id,
                    )
            except Exception as e:
                self.db.log("ERROR", f"Error en ejecución OANDA: {e}", self.worker_id)
            return

        # 3. EJECUCIÓN CON KALSHI (Eventos)
        if self.feeder_type == "kalshi":
            # Si hay llaves reales, ejecutamos orden firmada
            if self.kalshi_api_key_id and self.kalshi_private_key_path:
                try:
                    if requested_pct is not None:
                        spend_amount = quote_balance * requested_pct
                        contracts_count = int(spend_amount / price)
                    elif requested_amount is not None:
                        contracts_count = int(requested_amount)
                        spend_amount = contracts_count * price
                    else:
                        spend_amount = quote_balance * 0.5
                        contracts_count = int(spend_amount / price)

                    if contracts_count <= 0:
                        contracts_count = 10

                    price_cents = int(price * 100)

                    from cryptography.hazmat.primitives import hashes, serialization
                    from cryptography.hazmat.primitives.asymmetric import padding
                    import base64

                    with open(self.kalshi_private_key_path, "rb") as key_file:
                        private_key = serialization.load_pem_private_key(
                            key_file.read(), password=None
                        )

                    path = "/portfolio/orders"
                    timestamp = str(int(datetime.datetime.now().timestamp() * 1000))
                    method = "POST"

                    message = f"{timestamp}{method}{path}".encode("utf-8")
                    signature = private_key.sign(
                        message,
                        padding.PSS(
                            mgf=padding.MGF1(hashes.SHA256()),
                            salt_length=padding.PSS.MAX_LENGTH,
                        ),
                        hashes.SHA256(),
                    )
                    b64_sig = base64.b64encode(signature).decode("utf-8")

                    url = f"{self.kalshi_rest_url}{path}"
                    headers = {
                        "KALSHI-ACCESS-KEY": self.kalshi_api_key_id,
                        "KALSHI-ACCESS-SIGNATURE": b64_sig,
                        "KALSHI-ACCESS-TIMESTAMP": timestamp,
                        "Content-Type": "application/json",
                    }

                    side_to_place = "yes" if signal.side == "BUY" else "no"
                    order_data = {
                        "ticker": self.symbol,
                        "side": side_to_place,
                        "count": contracts_count,
                        "price": price_cents,
                        "type": "limit",
                        "action": "buy" if signal.side == "BUY" else "sell",
                        "client_order_id": str(uuid.uuid4()),
                    }

                    self.db.log(
                        "INFO",
                        f"Enviando orden a Kalshi: {signal.side} {contracts_count} contratos de {self.symbol}",
                        self.worker_id,
                    )
                    response = await asyncio.to_thread(
                        requests.post, url, headers=headers, json=order_data
                    )

                    if response.status_code in [200, 201]:
                        res_json = response.json()
                        order_id = res_json.get("order", {}).get("order_id", "N/A")
                        self.db.save_trade(
                            symbol=self.symbol,
                            side=signal.side,
                            price=price,
                            amount=float(contracts_count),
                            external_order_id=str(order_id),
                            status="COMPLETED",
                            worker_id=self.worker_id,
                            position_id=getattr(signal, "position_id", None),
                            trading_mode=self.trading_mode,
                        )
                        await self._sync_kalshi_portfolio()
                    else:
                        self.db.log(
                            "ERROR",
                            f"Fallo al enviar orden a Kalshi: {response.status_code} - {response.text}",
                            self.worker_id,
                        )
                except Exception as e:
                    self.db.log(
                        "ERROR", f"Error en ejecución Kalshi: {e}", self.worker_id
                    )
                return
            else:
                # Simulación local para Kalshi si no hay keys
                if signal.side == "BUY":
                    if requested_pct is not None:
                        spend_amount = quote_balance * requested_pct
                        contracts_count = spend_amount / price
                    elif requested_amount is not None:
                        spend_amount = requested_amount * price
                        contracts_count = requested_amount
                    else:
                        spend_amount = quote_balance * 0.5
                        contracts_count = spend_amount / price
                    new_quote = quote_balance - spend_amount
                    new_base = base_balance + contracts_count

                    self.db.save_trade(
                        symbol=self.symbol,
                        side="BUY",
                        price=price,
                        amount=contracts_count,
                        status="COMPLETED",
                        worker_id=self.worker_id,
                        position_id=getattr(signal, "position_id", None),
                        trading_mode=self.trading_mode,
                    )
                    self._update_db_portfolio(self.quote_asset, new_quote)
                    self._update_db_portfolio(self.base_asset, new_base)
                    self.db.log(
                        "INFO",
                        f"Compra de eventos simulada (Kalshi). Nuevo saldo: {new_quote:.2f} {self.quote_asset}, {new_base:.2f} contratos YES.",
                        self.worker_id,
                    )
                else:
                    if base_balance <= 0:
                        self.db.log(
                            "WARNING",
                            "Sin contratos en portafolio para vender.",
                            self.worker_id,
                        )
                        return
                    if requested_pct is not None:
                        amount_to_sell = min(base_balance * requested_pct, base_balance)
                    elif requested_amount is not None:
                        amount_to_sell = min(requested_amount, base_balance)
                    else:
                        amount_to_sell = base_balance
                    revenue = amount_to_sell * price
                    new_quote = quote_balance + revenue
                    new_base = base_balance - amount_to_sell

                    self.db.save_trade(
                        symbol=self.symbol,
                        side="SELL",
                        price=price,
                        amount=amount_to_sell,
                        status="COMPLETED",
                        worker_id=self.worker_id,
                        position_id=getattr(signal, "position_id", None),
                        trading_mode=self.trading_mode,
                    )
                    self._update_db_portfolio(self.quote_asset, new_quote)
                    self._update_db_portfolio(self.base_asset, new_base)
                    self.db.log(
                        "INFO",
                        f"Venta de contratos simulada (Kalshi). Nuevo saldo: {new_quote:.2f} {self.quote_asset}, {new_base:.2f} contratos.",
                        self.worker_id,
                    )
                return

        # 4. SIMULACIÓN LOCAL MOCK / FALLBACK GENERAL
        if signal.side == "BUY":
            if requested_pct is not None:
                spend_amount = quote_balance * requested_pct
                amount_to_buy = spend_amount / price
            elif requested_amount is not None:
                amount_to_buy = requested_amount
                spend_amount = amount_to_buy * price
            else:
                spend_amount = quote_balance * 0.5
                amount_to_buy = spend_amount / price

            if quote_balance < spend_amount:
                self.db.log(
                    "WARNING",
                    f"Saldo insuficiente. Requerido: {spend_amount:.2f} {self.quote_asset}, Disponible: {quote_balance:.2f} {self.quote_asset}.",
                    self.worker_id,
                )
                return

            new_quote = quote_balance - spend_amount
            new_base = base_balance + amount_to_buy

            self.db.save_trade(
                symbol=self.symbol,
                side="BUY",
                price=price,
                amount=amount_to_buy,
                status="COMPLETED",
                worker_id=self.worker_id,
                position_id=getattr(signal, "position_id", None),
                trading_mode=self.trading_mode,
            )
            self._update_db_portfolio(self.quote_asset, new_quote)
            self._update_db_portfolio(self.base_asset, new_base)

            pos_symbol = getattr(signal, "symbol", self.symbol)
            if not getattr(signal, "position_id", None):
                position_id = self.db.save_position(
                    self.worker_id,
                    pos_symbol,
                    "BUY",
                    price,
                    amount_to_buy,
                )
                if position_id and hasattr(self.strategy, "_arb_groups"):
                    for gid, grp in self.strategy._arb_groups.items():
                        if pos_symbol.startswith(gid):
                            grp.setdefault("position_ids", []).append(position_id)
                            break
                if (
                    position_id
                    and hasattr(self.strategy, "_position_id")
                    and not self.strategy._position_id
                ):
                    self.strategy._position_id = position_id

            self.db.log(
                "INFO",
                f"Compra simulada completada. Nuevo saldo: {new_quote:.2f} {self.quote_asset}, {new_base:.6f} {self.base_asset}",
                self.worker_id,
            )
        elif signal.side == "SELL":
            if requested_pct is not None:
                amount_to_sell = min(base_balance * requested_pct, base_balance)
            elif requested_amount is not None:
                amount_to_sell = min(requested_amount, base_balance)
            else:
                amount_to_sell = base_balance

            if base_balance < amount_to_sell:
                self.db.log(
                    "WARNING",
                    f"Sin {self.base_asset} suficiente en cartera. Requerido: {amount_to_sell:.6f}, Disponible: {base_balance:.6f}.",
                    self.worker_id,
                )
                return

            revenue = amount_to_sell * price
            new_quote = quote_balance + revenue
            new_base = base_balance - amount_to_sell

            self.db.save_trade(
                symbol=self.symbol,
                side="SELL",
                price=price,
                amount=amount_to_sell,
                status="COMPLETED",
                worker_id=self.worker_id,
                position_id=getattr(signal, "position_id", None),
                trading_mode=self.trading_mode,
            )
            self._update_db_portfolio(self.quote_asset, new_quote)
            self._update_db_portfolio(self.base_asset, new_base)

            pos_symbol = getattr(signal, "symbol", self.symbol)
            open_pos = self.db.get_open_positions(worker_id=self.worker_id)
            matched = [p for p in open_pos if p["symbol"] == pos_symbol]
            if matched:
                self.db.close_position(
                    matched[0]["id"], price, signal.reason, worker_id=self.worker_id
                )

            self.db.log(
                "INFO",
                f"Venta simulada completada. Nuevo saldo: {new_quote:.2f} {self.quote_asset}, {new_base:.6f} {self.base_asset}",
                self.worker_id,
            )

    async def _sync_alpaca_portfolio(self):
        if self.execution_type == "simulation":
            return
        if not self.alpaca_client or self.feeder_type != "alpaca":
            return

        try:
            self.db.log(
                "INFO", "Sincronizando portafolio con Alpaca...", self.worker_id
            )
            account = await asyncio.to_thread(self.alpaca_client.get_account)
            cash = float(account.cash)
            self._update_db_portfolio(self.quote_asset, cash)

            positions = await asyncio.to_thread(self.alpaca_client.get_all_positions)
            base_qty = 0.0
            alpaca_target_symbol = self.feeder.symbol.replace("/", "").upper()

            for position in positions:
                if position.symbol.upper() == alpaca_target_symbol:
                    base_qty = float(position.qty)
                    break
            self._update_db_portfolio(self.base_asset, base_qty)
            self.db.log(
                "INFO",
                f"Sincronización de Alpaca exitosa. {self.quote_asset}: {cash:.2f}, {self.base_asset}: {base_qty:.6f}",
                self.worker_id,
            )

            # Sincronizar estado de órdenes pendientes con Alpaca
            pending_trades = self.db.get_pending_trades(self.worker_id)
            for trade in pending_trades:
                ext_id = trade.get("external_order_id")
                if ext_id:
                    try:
                        order_detail = await asyncio.to_thread(
                            self.alpaca_client.get_order_by_id, ext_id
                        )
                        current_status = (
                            str(order_detail.status.value).upper()
                            if hasattr(order_detail.status, "value")
                            else str(order_detail.status).upper()
                        )
                        if current_status == "FILLED":
                            self.db.update_trade_status(ext_id, "COMPLETED")
                            self.db.log(
                                "INFO",
                                f"Orden {ext_id} completada y marcada como COMPLETED en la base de datos.",
                                self.worker_id,
                            )
                        elif current_status in ["CANCELED", "EXPIRED", "REJECTED"]:
                            self.db.update_trade_status(ext_id, current_status)
                            self.db.log(
                                "INFO",
                                f"Orden {ext_id} cancelada/expirada en Alpaca. Estado DB: {current_status}.",
                                self.worker_id,
                            )
                    except Exception:
                        pass
        except Exception as e:
            self.db.log(
                "ERROR", f"Error al sincronizar con Alpaca: {e}", self.worker_id
            )

    async def _sync_oanda_portfolio(self):
        if not self.oanda_account_id or not self.oanda_token:
            return
        try:
            self.db.log("INFO", "Sincronizando portafolio con OANDA...", self.worker_id)
            response = await asyncio.to_thread(
                requests.get,
                self.oanda_rest_url,
                headers={
                    "Authorization": f"Bearer {self.oanda_token}",
                    "Content-Type": "application/json",
                },
            )
            if response.status_code == 200:
                data = response.json()
                account = data.get("account", {})
                balance = float(account.get("balance", 0.0))
                self._update_db_portfolio(self.quote_asset, balance)

                positions = account.get("positions", [])
                base_qty = 0.0
                for pos in positions:
                    if pos.get("instrument") == self.feeder.symbol:
                        long_units = float(pos.get("long", {}).get("units", 0.0))
                        short_units = float(pos.get("short", {}).get("units", 0.0))
                        base_qty = long_units - short_units
                        break
                self._update_db_portfolio(self.base_asset, base_qty)
                self.db.log(
                    "INFO",
                    f"Sincronización de OANDA exitosa. {self.quote_asset}: {balance:.2f}, {self.base_asset}: {base_qty:.2f}",
                    self.worker_id,
                )
            else:
                self.db.log(
                    "ERROR",
                    f"Fallo al sincronizar portafolio con OANDA. Status: {response.status_code}",
                    self.worker_id,
                )
        except Exception as e:
            self.db.log("ERROR", f"Error al sincronizar con OANDA: {e}", self.worker_id)

    async def _sync_kalshi_portfolio(self):
        if self.execution_type == "simulation":
            return
        if not self.kalshi_api_key_id or not self.kalshi_private_key_path:
            return
        try:
            # Sincronización real de balance de la cuenta de Kalshi v2
            from cryptography.hazmat.primitives import hashes, serialization
            from cryptography.hazmat.primitives.asymmetric import padding
            import base64

            with open(self.kalshi_private_key_path, "rb") as key_file:
                private_key = serialization.load_pem_private_key(
                    key_file.read(), password=None
                )

            path = "/portfolio/balance"
            timestamp = str(int(datetime.datetime.now().timestamp() * 1000))
            message = f"{timestamp}GET{path}".encode("utf-8")
            signature = private_key.sign(
                message,
                padding.PSS(
                    mgf=padding.MGF1(hashes.SHA256()),
                    salt_length=padding.PSS.MAX_LENGTH,
                ),
                hashes.SHA256(),
            )
            b64_sig = base64.b64encode(signature).decode("utf-8")

            response = await asyncio.to_thread(
                requests.get,
                f"{self.kalshi_rest_url}{path}",
                headers={
                    "KALSHI-ACCESS-KEY": self.kalshi_api_key_id,
                    "KALSHI-ACCESS-SIGNATURE": b64_sig,
                    "KALSHI-ACCESS-TIMESTAMP": timestamp,
                    "Content-Type": "application/json",
                },
            )
            if response.status_code == 200:
                data = response.json()
                balance_cents = float(data.get("balance", 0.0))
                balance = balance_cents / 100.0
                self._update_db_portfolio(self.quote_asset, balance)
                self.db.log(
                    "INFO",
                    f"Sincronización de Kalshi exitosa. USD: {balance:.2f}",
                    self.worker_id,
                )
            else:
                self.db.log(
                    "ERROR",
                    f"Fallo al sincronizar con Kalshi. Status: {response.status_code}",
                    self.worker_id,
                )
        except Exception as e:
            self.db.log(
                "ERROR", f"Error al sincronizar con Kalshi: {e}", self.worker_id
            )

    async def _warm_up_strategy(self):
        try:
            if self.feeder_type == "alpaca":
                self.db.log(
                    "INFO",
                    f"Pre-cargando historial de {self.symbol} desde Alpaca...",
                    self.worker_id,
                )
                api_key = os.getenv("ALPACA_API_KEY")
                secret_key = os.getenv("ALPACA_SECRET_KEY")
                is_crypto = (
                    self.feeder.is_crypto if hasattr(self.feeder, "is_crypto") else True
                )
                bar_interval = (
                    self.strategy.bar_interval
                    if hasattr(self.strategy, "bar_interval")
                    else 60
                )

                from alpaca.data.timeframe import TimeFrame

                if bar_interval <= 60:
                    tf = TimeFrame.Minute
                    minutes_back = 2000  # Incrementar para evitar el vacío por retraso del feed gratuito de Alpaca (gap de ~5 horas)
                elif bar_interval <= 300:
                    tf = TimeFrame.Minute
                    minutes_back = 5000
                else:
                    tf = TimeFrame.Hour
                    minutes_back = 10000

                from datetime import timedelta, timezone

                start_time = datetime.datetime.now(timezone.utc) - timedelta(
                    minutes=minutes_back
                )

                import pandas as pd

                if is_crypto:
                    from alpaca.data.historical import CryptoHistoricalDataClient
                    from alpaca.data.requests import CryptoBarsRequest

                    client = CryptoHistoricalDataClient(api_key, secret_key)
                    request_params = CryptoBarsRequest(
                        symbol_or_symbols=self.feeder.symbol,
                        timeframe=tf,
                        start=start_time,
                        end=datetime.datetime.now(timezone.utc),
                    )
                    bars = await asyncio.to_thread(
                        client.get_crypto_bars, request_params
                    )
                else:
                    from alpaca.data.historical import StockHistoricalDataClient
                    from alpaca.data.requests import StockBarsRequest

                    client = StockHistoricalDataClient(api_key, secret_key)
                    request_params = StockBarsRequest(
                        symbol_or_symbols=self.feeder.symbol,
                        timeframe=tf,
                        start=start_time,
                        end=datetime.datetime.now(timezone.utc),
                    )
                    bars = await asyncio.to_thread(
                        client.get_stock_bars, request_params
                    )

                if bars and self.feeder.symbol in bars.data:
                    symbol_bars = bars.data[self.feeder.symbol]
                    rows = []
                    for b in symbol_bars:
                        dt = b.timestamp.astimezone()
                        dt_naive = dt.replace(tzinfo=None)
                        rows.append(
                            {
                                "timestamp": dt_naive,
                                "open": float(b.open),
                                "high": float(b.high),
                                "low": float(b.low),
                                "close": float(b.close),
                                "price": float(b.close),
                            }
                        )
                    hist_df = pd.DataFrame(rows)
                    self.strategy.prices_df = hist_df.sort_values(
                        "timestamp"
                    ).reset_index(drop=True)
                    self.db.log(
                        "INFO",
                        f"Pre-carga completada. {len(self.strategy.prices_df)} velas cargadas.",
                        self.worker_id,
                    )
                else:
                    self.db.log(
                        "WARNING",
                        "No se recibieron barras históricas de Alpaca. Generando fallback sintético...",
                        self.worker_id,
                    )
                    await self._generate_synthetic_history()
            elif self.feeder_type in ("limitless", "limitless_sports", "kalshi", "polymarket", "binary_arb", "multi_signal"):
                self.db.log(
                    "INFO",
                    f"{self.feeder_type}: omitiendo historial sintético (esperando datos reales del feeder)...",
                    self.worker_id,
                )
            else:
                # Otros feeders (simulación / paper): Generar historial sintético para evitar arrancar con pantalla en blanco
                await self._generate_synthetic_history()

        except Exception as e:
            self.db.log(
                "ERROR",
                f"Error al pre-cargar datos históricos: {e}.",
                self.worker_id,
            )
            if self.feeder_type not in ("limitless", "limitless_sports", "kalshi", "polymarket", "binary_arb", "multi_signal"):
                try:
                    await self._generate_synthetic_history()
                except Exception:
                    pass

    async def _generate_synthetic_history(self):
        try:
            self.db.log(
                "INFO",
                f"Generando historial sintético para {self.symbol} ({self.feeder_type})...",
                self.worker_id,
            )
            import pandas as pd
            import random

            # Determinar precio inicial realista
            if "BTC" in self.symbol:
                start_price = 65000.0
            elif "ETH" in self.symbol:
                start_price = 3500.0
            elif "SOL" in self.symbol:
                start_price = 140.0
            elif self.feeder_type in ["kalshi", "polymarket", "limitless", "limitless_sports"]:
                start_price = 0.50
            else:
                start_price = 100.0

            # Generar 120 velas de 1 minuto hacia atrás
            now = datetime.datetime.now()
            rows = []
            current_price = start_price
            for i in range(120, 0, -1):
                dt = now - datetime.timedelta(minutes=i)
                # Camino aleatorio (Random Walk)
                if "BTC" in self.symbol or "ETH" in self.symbol or "SOL" in self.symbol:
                    change = random.uniform(-0.003, 0.003)
                    current_price = max(1.0, current_price * (1 + change))
                elif self.feeder_type in [
                    "kalshi",
                    "polymarket",
                    "limitless",
                    "limitless_sports",
                ]:
                    change = random.uniform(-0.015, 0.015)
                    current_price = max(0.05, min(0.95, current_price + change))
                else:
                    change = random.uniform(-0.003, 0.003)
                    current_price = max(1.0, current_price * (1 + change))

                # Crear valores OHLC realistas
                open_p = current_price
                close_p = current_price * (1 + random.uniform(-0.001, 0.001))
                high_p = max(open_p, close_p) * (1 + random.uniform(0, 0.002))
                low_p = min(open_p, close_p) * (1 - random.uniform(0, 0.002))

                rows.append(
                    {
                        "timestamp": dt,
                        "open": open_p,
                        "high": high_p,
                        "low": low_p,
                        "close": close_p,
                        "price": close_p,
                    }
                )

            self.strategy.prices_df = pd.DataFrame(rows)
            self.db.log(
                "INFO",
                f"Historial sintético generado. {len(self.strategy.prices_df)} velas cargadas.",
                self.worker_id,
            )
        except Exception as e:
            self.db.log(
                "ERROR", f"Error al generar historial sintético: {e}", self.worker_id
            )


class TradingEngine:
    def __init__(self, db: DatabaseManager):
        self.db = db
        self.workers = {}
        self._load_workers()
        self._setup_log_broadcast()

    def _setup_log_broadcast(self):
        """Registra un hook en DatabaseManager para transmitir logs vía WebSocket."""

        def broadcast_log(level, message, worker_id, timestamp):
            try:
                asyncio.get_event_loop().create_task(
                    ws_server.broadcast(
                        worker_id,
                        make_event(
                            "log",
                            {
                                "level": level,
                                "message": message,
                                "timestamp": timestamp.isoformat(),
                                "worker_id": worker_id,
                            },
                        ),
                    )
                )
            except Exception:
                pass  # El broadcast de logs nunca debe romper el flujo principal

        self.db.add_log_hook(broadcast_log)

    def _load_workers(self):
        # Intentar leer configuraciones de múltiples workers de .env
        w1_enabled = os.getenv("WORKER1_ENABLED", "true").lower() == "true"
        w2_enabled = os.getenv("WORKER2_ENABLED", "true").lower() == "true"
        w3_enabled = os.getenv("WORKER3_ENABLED", "true").lower() == "true"

        if w1_enabled:
            w1_type = os.getenv(
                "WORKER1_FEEDER_TYPE", os.getenv("FEEDER_TYPE", "alpaca")
            )
            w1_sym = os.getenv("WORKER1_SYMBOL", os.getenv("TRADING_SYMBOL", "BTC/USD"))
            self.workers["worker_1"] = TradingWorker(
                "worker_1", "Alpaca Ventana", w1_sym, w1_type, self.db
            )

        if w2_enabled:
            w2_type = os.getenv("WORKER2_FEEDER_TYPE", "limitless")
            w2_sym = os.getenv("WORKER2_SYMBOL", "fed-rate-july-2026")
            self.workers["worker_2"] = TradingWorker(
                "worker_2", "Limitless Macro", w2_sym, w2_type, self.db
            )

        if w3_enabled:
            w3_type = os.getenv("WORKER3_FEEDER_TYPE", "limitless_sports")
            w3_sym = os.getenv(
                "WORKER3_SYMBOL",
                "SPORTS",
            )
            self.workers["worker_3"] = TradingWorker(
                "worker_3", "Limitless Sports", w3_sym, w3_type, self.db
            )

        w4_enabled = os.getenv("WORKER4_ENABLED", "false").lower() == "true"
        if w4_enabled:
            w4_type = os.getenv("WORKER4_FEEDER_TYPE", "binary_arb")
            w4_sym = os.getenv("WORKER4_SYMBOL", "BINARY_ARB")
            self.workers["worker_4"] = TradingWorker(
                "worker_4", "Binary Arb", w4_sym, w4_type, self.db
            )

    @property
    def is_running(self):
        return any(w.is_running for w in self.workers.values())

    @property
    def symbol(self):
        return (
            self.workers.get("worker_1").symbol if "worker_1" in self.workers else "-"
        )

    @property
    def feeder_type(self):
        return (
            self.workers.get("worker_1").feeder_type
            if "worker_1" in self.workers
            else "mock"
        )

    @property
    def base_asset(self):
        return (
            self.workers.get("worker_1").base_asset
            if "worker_1" in self.workers
            else "-"
        )

    @property
    def quote_asset(self):
        return (
            self.workers.get("worker_1").quote_asset
            if "worker_1" in self.workers
            else "-"
        )

    @property
    def strategy(self):
        return (
            self.workers.get("worker_1").strategy
            if "worker_1" in self.workers
            else None
        )

    async def start(self, worker_id: str = None):
        if worker_id:
            if worker_id in self.workers:
                await self.workers[worker_id].start()
        else:
            for w in self.workers.values():
                await w.start()

    async def stop(self, worker_id: str = None):
        if worker_id:
            if worker_id in self.workers:
                await self.workers[worker_id].stop()
        else:
            for w in self.workers.values():
                await w.stop()
