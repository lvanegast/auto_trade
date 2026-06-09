import asyncio
import os
import requests
from src.database import DatabaseManager
from src.events import SignalEvent
from src.strategy.ema_rsi import EmaRsiStrategy
from src.feeders.mock_feeder import MockFeeder
from src.feeders.oanda_feeder import OandaFeeder
from src.feeders.ig_feeder import IGFeeder
from src.feeders.alpaca_feeder import AlpacaFeeder


class TradingEngine:
    def __init__(self, db: DatabaseManager):
        self.db = db
        self.queue = asyncio.Queue()

        # Cargar configuración desde el entorno
        self.feeder_type = os.getenv("FEEDER_TYPE", "mock").lower()
        self.symbol = os.getenv("TRADING_SYMBOL", "BTCUSDT").upper()

        # Desglosar base y quote asset (ej: BTC_USDT -> BTC y USDT)
        self.base_asset, self.quote_asset = self._parse_symbol()

        # Inicializar componentes
        self.strategy = EmaRsiStrategy(self.symbol)

        if self.feeder_type == "oanda":
            self.feeder = OandaFeeder(self.symbol, self.queue)
        elif self.feeder_type == "ig":
            self.feeder = IGFeeder(self.symbol, self.queue)
        elif self.feeder_type == "alpaca":
            self.feeder = AlpacaFeeder(self.symbol, self.queue)
        else:
            self.feeder = MockFeeder(self.symbol, self.queue, interval=1.0)

        # Estado del motor
        self.is_running = False
        self.engine_task = None
        self.feeder_task = None

        # Cliente de ejecución para Alpaca
        self.alpaca_client = None
        if self.feeder_type == "alpaca":
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
                )
            else:
                self.db.log(
                    "WARNING",
                    "Cliente de ejecución de Alpaca no configurado debido a credenciales faltantes o por defecto.",
                )

        # Credenciales e URL para OANDA
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

        # Saldo virtual inicial en base de datos para simulación
        self._init_portfolio()

    def _parse_symbol(self) -> tuple:
        """Separa el símbolo en activo base y activo cotizado (base, quote)."""
        symbol = self.symbol

        # Soporte para epics de IG Group (ej: CS.D.EURUSD.TODAY.IP)
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

        # Reglas comunes para separar sin guión bajo
        if symbol.startswith("BTC"):
            return "BTC", "USDT"
        elif symbol.startswith("EUR"):
            return "EUR", "USD"
        elif symbol.startswith("GBP"):
            return "GBP", "USD"

        # Fallback genérico: mitad y mitad
        mid = len(symbol) // 2
        return symbol[:mid], symbol[mid:]

    def _init_portfolio(self):
        """Inicializa un balance virtual en PostgreSQL si no existe."""
        # Si usamos Alpaca u OANDA, la sincronización real se hará al iniciar (start)
        if self.alpaca_client or (
            self.feeder_type == "oanda" and self.oanda_account_id and self.oanda_token
        ):
            return

        portfolio = self.db.get_portfolio()
        assets = [item["asset"] for item in portfolio]

        # Cargar saldo inicial si no está registrado
        if self.quote_asset not in assets:
            self.db.update_portfolio(
                self.quote_asset, 10000.0
            )  # 10,000 unidades virtuales de la divisa cotizada
            self.db.log(
                "INFO",
                f"Portafolio inicializado con 10,000 {self.quote_asset} para simulación.",
            )
        if self.base_asset not in assets:
            self.db.update_portfolio(self.base_asset, 0.0)

    async def start(self):
        """Inicia el motor de trading en segundo plano."""
        if self.is_running:
            return

        self.is_running = True
        self.db.set_state("bot_running", "true")
        self.db.log(
            "INFO",
            f"Iniciando motor de trading ({self.feeder_type.upper()}) para {self.symbol}...",
        )

        # Sincronizar balances reales si usamos Alpaca u OANDA
        if self.alpaca_client:
            await self._sync_alpaca_portfolio()
        elif self.feeder_type == "oanda" and self.oanda_account_id and self.oanda_token:
            await self._sync_oanda_portfolio()

        # Pre-cargar datos históricos para evitar arranque en frío (cold start)
        if self.feeder_type == "alpaca":
            await self._warm_up_strategy()

        # Arrancar loops asíncronos
        self.engine_task = asyncio.create_task(self._event_loop())
        self.feeder_task = asyncio.create_task(self.feeder.start())

    async def stop(self):
        """Detiene el motor de trading."""
        if not self.is_running:
            return

        self.is_running = False
        self.db.set_state("bot_running", "false")
        self.db.log("INFO", "Deteniendo motor de trading...")

        # Detener alimentador
        self.feeder.stop()

        # Cancelar tareas asíncronas
        if self.feeder_task:
            self.feeder_task.cancel()
        if self.engine_task:
            self.engine_task.cancel()

        self.feeder_task = None
        self.engine_task = None

    async def _event_loop(self):
        """Loop asíncrono principal que procesa la cola de eventos."""
        print(f"[Engine] Loop de eventos iniciado para {self.symbol}.")
        try:
            while self.is_running:
                # Leer el siguiente evento de la cola
                event = await self.queue.get()

                try:
                    if event.event_type == "PRICE_UPDATE":
                        # Pasar precio actual a la estrategia
                        signal = self.strategy.on_price_update(event)
                        if signal:
                            # Meter señal generada a la cola
                            await self.queue.put(signal)

                    elif event.event_type == "SIGNAL":
                        # Procesar señal para ejecución
                        await self._execute_order(event)

                except Exception as e:
                    self.db.log(
                        "ERROR",
                        f"Error en event_loop procesando evento {event.event_type}: {e}",
                    )
                finally:
                    self.queue.task_done()
        except asyncio.CancelledError:
            print("[Engine] Loop de eventos cancelado.")

    async def _execute_order(self, signal: SignalEvent):
        """Maneja la ejecución de órdenes (reales/demo en Alpaca, OANDA o simulación local)."""
        self.db.log("INFO", f"Procesando señal: {signal}")

        # Cargar balances actuales de base de datos
        balances = {
            item["asset"]: float(item["free_balance"])
            for item in self.db.get_portfolio()
        }
        quote_balance = balances.get(self.quote_asset, 0.0)
        base_balance = balances.get(self.base_asset, 0.0)

        price = signal.price

        # 1. EJECUCIÓN CON ALPACA (Demo/Real)
        if self.alpaca_client:
            from alpaca.trading.requests import MarketOrderRequest
            from alpaca.trading.enums import OrderSide, TimeInForce

            try:
                # Determinar cantidad para colocar la orden
                if signal.side == "BUY":
                    # Comprar con el 50% de la divisa cotizada disponible
                    spend_amount = quote_balance * 0.5
                    amount_to_buy = spend_amount / price

                    # Criptomonedas aceptan fracciones altas; acciones suelen ser más limitadas
                    is_crypto_symbol = "/" in self.feeder.symbol
                    qty = (
                        round(amount_to_buy, 6)
                        if is_crypto_symbol
                        else round(amount_to_buy, 4)
                    )

                    if qty <= 0:
                        self.db.log(
                            "WARNING",
                            "Cantidad a comprar calculada es 0. Abortando orden en Alpaca.",
                        )
                        return

                    order_data = MarketOrderRequest(
                        symbol=self.feeder.symbol.replace(
                            "/", ""
                        ),  # Ej. BTC/USD -> BTCUSD
                        qty=qty,
                        side=OrderSide.BUY,
                        time_in_force=TimeInForce.GTC,
                    )
                else:
                    # Vender el 100% del activo base
                    is_crypto_symbol = "/" in self.feeder.symbol
                    qty = (
                        round(base_balance, 6)
                        if is_crypto_symbol
                        else round(base_balance, 4)
                    )

                    if qty <= 0:
                        self.db.log(
                            "WARNING",
                            "Cantidad a vender es 0 o insuficiente. Abortando orden en Alpaca.",
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
                    f"Enviando orden de mercado a Alpaca: {order_data.side} {order_data.qty} {order_data.symbol}",
                )

                # Ejecutar llamada API en hilo secundario para no bloquear
                order = await asyncio.to_thread(
                    self.alpaca_client.submit_order, order_data=order_data
                )

                # Registrar en base de datos local
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
                )
                self.db.log(
                    "INFO",
                    f"Orden enviada con éxito. ID externo: {order.id}, Estado: {order.status}",
                )

                # Sincronizar balances locales con los de la cuenta de Alpaca después del trade
                await self._sync_alpaca_portfolio()

            except Exception as e:
                self.db.log("ERROR", f"Fallo al enviar orden a Alpaca: {e}")
            return

        # 2. EJECUCIÓN CON OANDA (Demo/Real)
        if self.feeder_type == "oanda" and self.oanda_account_id and self.oanda_token:
            try:
                # OANDA unidades: tamaño de posición.
                # Calculamos las unidades a operar usando el balance disponible de la divisa cotizada.
                units = int(quote_balance * 0.5)
                if units <= 0:
                    units = 1000  # Micro lote por defecto

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
                    f"Enviando orden a OANDA: {signal.side} {abs(units)} unidades de {self.feeder.symbol}",
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
                    )
                    self.db.log(
                        "INFO",
                        f"Orden ejecutada en OANDA con éxito. ID Transacción: {trade_id}",
                    )
                    await self._sync_oanda_portfolio()
                else:
                    self.db.log(
                        "ERROR",
                        f"Fallo al ejecutar orden en OANDA. Status: {response.status_code}, Detalle: {response.text}",
                    )

            except Exception as e:
                self.db.log("ERROR", f"Error al ejecutar orden en OANDA: {e}")
            return

        # 3. EJECUCIÓN SIMULADA LOCAL (Fallback si no hay Alpaca ni OANDA)
        if signal.side == "BUY":
            spend_amount = quote_balance * 0.5
            min_spend = 10.0 if self.quote_asset in ["USDT", "USD"] else 1.0
            if spend_amount < min_spend:
                self.db.log(
                    "WARNING",
                    f"Saldo {self.quote_asset} insuficiente para realizar compra simulada.",
                )
                return

            amount_to_buy = spend_amount / price
            new_quote = quote_balance - spend_amount
            new_base = base_balance + amount_to_buy

            self.db.save_trade(
                symbol=self.symbol,
                side="BUY",
                price=price,
                amount=amount_to_buy,
                status="COMPLETED",
            )

            self.db.update_portfolio(self.quote_asset, new_quote)
            self.db.update_portfolio(self.base_asset, new_base)
            self.db.log(
                "INFO",
                f"Compra simulada completada. Nuevo saldo: {new_quote:.2f} {self.quote_asset}, {new_base:.6f} {self.base_asset}",
            )

        elif signal.side == "SELL":
            min_sell = 0.0001 if self.base_asset == "BTC" else 1.0
            if base_balance < min_sell:
                self.db.log(
                    "WARNING",
                    f"Sin {self.base_asset} suficiente en cartera para realizar venta simulada.",
                )
                return

            revenue = base_balance * price
            new_quote = quote_balance + revenue
            new_base = 0.0

            self.db.save_trade(
                symbol=self.symbol,
                side="SELL",
                price=price,
                amount=base_balance,
                status="COMPLETED",
            )

            self.db.update_portfolio(self.quote_asset, new_quote)
            self.db.update_portfolio(self.base_asset, new_base)
            self.db.log(
                "INFO",
                f"Venta simulada completada. Nuevo saldo: {new_quote:.2f} {self.quote_asset}, {new_base:.6f} {self.base_asset}",
            )

    async def _sync_alpaca_portfolio(self):
        """Sincroniza los balances del portafolio local con los reales de la cuenta de Alpaca."""
        if not self.alpaca_client:
            return

        try:
            self.db.log("INFO", "Sincronizando portafolio con Alpaca...")

            # Obtener datos de la cuenta (Efectivo disponible)
            account = await asyncio.to_thread(self.alpaca_client.get_account)
            cash = float(account.cash)

            # Actualizar el balance del quote asset (ej. USD o USDT) en Postgres
            self.db.update_portfolio(self.quote_asset, cash)

            # Obtener posiciones abiertas
            positions = await asyncio.to_thread(self.alpaca_client.get_all_positions)

            # Por defecto, asumimos que no hay tenencias del activo base
            base_qty = 0.0

            # Formato esperado del ticker en las posiciones de Alpaca (ej. BTCUSD o AAPL)
            alpaca_target_symbol = self.feeder.symbol.replace("/", "").upper()

            for position in positions:
                if position.symbol.upper() == alpaca_target_symbol:
                    base_qty = float(position.qty)
                    break

            # Actualizar balance del base asset (ej. BTC) en Postgres
            self.db.update_portfolio(self.base_asset, base_qty)
            self.db.log(
                "INFO",
                f"Sincronización de Alpaca exitosa. Balances actualizados en base de datos. {self.quote_asset}: {cash:.2f}, {self.base_asset}: {base_qty:.6f}",
            )

        except Exception as e:
            self.db.log("ERROR", f"Error al sincronizar balances con Alpaca: {e}")

    async def _sync_oanda_portfolio(self):
        """Sincroniza los balances del portafolio local con los reales de la cuenta de OANDA."""
        if not self.oanda_account_id or not self.oanda_token:
            return

        try:
            self.db.log("INFO", "Sincronizando portafolio con OANDA...")
            url = self.oanda_rest_url
            headers = {
                "Authorization": f"Bearer {self.oanda_token}",
                "Content-Type": "application/json",
            }

            response = await asyncio.to_thread(requests.get, url, headers=headers)

            if response.status_code == 200:
                data = response.json()
                account = data.get("account", {})
                balance = float(account.get("balance", 0.0))
                self.db.update_portfolio(self.quote_asset, balance)

                positions = account.get("positions", [])
                base_qty = 0.0

                for pos in positions:
                    if pos.get("instrument") == self.feeder.symbol:
                        long_units = float(pos.get("long", {}).get("units", 0.0))
                        short_units = float(pos.get("short", {}).get("units", 0.0))
                        base_qty = long_units - short_units
                        break

                self.db.update_portfolio(self.base_asset, base_qty)
                self.db.log(
                    "INFO",
                    f"Sincronización de OANDA exitosa. {self.quote_asset}: {balance:.2f}, {self.base_asset}: {base_qty:.2f}",
                )
            else:
                self.db.log(
                    "ERROR",
                    f"Fallo al sincronizar portafolio con OANDA. Status: {response.status_code}",
                )

        except Exception as e:
            self.db.log("ERROR", f"Error al sincronizar balances con OANDA: {e}")

    async def _warm_up_strategy(self):
        """Pre-carga datos históricos en la estrategia para evitar el arranque en frío (cold start)."""
        if self.feeder_type != "alpaca":
            return

        try:
            self.db.log(
                "INFO", f"Pre-cargando historial de {self.symbol} desde Alpaca..."
            )
            api_key = os.getenv("ALPACA_API_KEY")
            secret_key = os.getenv("ALPACA_SECRET_KEY")

            # Determinar si es crypto o stock
            is_crypto = (
                self.feeder.is_crypto if hasattr(self.feeder, "is_crypto") else True
            )

            # Obtener intervalo de barra (por defecto 60 segundos)
            bar_interval = (
                self.strategy.bar_interval
                if hasattr(self.strategy, "bar_interval")
                else 60
            )

            # Mapear bar_interval a timeframe de Alpaca
            from alpaca.data.timeframe import TimeFrame

            if bar_interval <= 60:
                tf = TimeFrame.Minute
                minutes_back = 100
            elif bar_interval <= 300:
                tf = TimeFrame.Minute
                minutes_back = 500
            else:
                tf = TimeFrame.Hour
                minutes_back = 2400

            from datetime import datetime, timedelta, timezone

            start_time = datetime.now(timezone.utc) - timedelta(minutes=minutes_back)

            # Crear cliente de datos históricos
            import pandas as pd

            if is_crypto:
                from alpaca.data.historical import CryptoHistoricalDataClient
                from alpaca.data.requests import CryptoBarsRequest

                client = CryptoHistoricalDataClient(api_key, secret_key)
                request_params = CryptoBarsRequest(
                    symbol_or_symbols=self.feeder.symbol,
                    timeframe=tf,
                    start=start_time,
                    end=datetime.now(timezone.utc),
                )
                # Ejecutar en hilo secundario para no bloquear
                bars = await asyncio.to_thread(client.get_crypto_bars, request_params)
            else:
                from alpaca.data.historical import StockHistoricalDataClient
                from alpaca.data.requests import StockBarsRequest

                client = StockHistoricalDataClient(api_key, secret_key)
                request_params = StockBarsRequest(
                    symbol_or_symbols=self.feeder.symbol,
                    timeframe=tf,
                    start=start_time,
                    end=datetime.now(timezone.utc),
                )
                bars = await asyncio.to_thread(client.get_stock_bars, request_params)

            if bars and self.feeder.symbol in bars.data:
                symbol_bars = bars.data[self.feeder.symbol]

                # Convertir a filas en prices_df
                rows = []
                for b in symbol_bars:
                    # Convertir timestamp a local naive
                    dt = b.timestamp.astimezone()
                    dt_naive = dt.replace(tzinfo=None)
                    rows.append({"timestamp": dt_naive, "price": float(b.close)})

                # Crear DataFrame y agregarlo a la estrategia
                hist_df = pd.DataFrame(rows)
                self.strategy.prices_df = hist_df.sort_values("timestamp").reset_index(
                    drop=True
                )
                self.db.log(
                    "INFO",
                    f"Pre-carga completada. {len(self.strategy.prices_df)} barras históricas cargadas en la estrategia.",
                )
            else:
                self.db.log(
                    "WARNING",
                    "No se recibieron datos históricos de Alpaca para pre-cargar.",
                )

        except Exception as e:
            self.db.log("ERROR", f"Error al pre-cargar datos históricos: {e}")
