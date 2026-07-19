import os
import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2.pool import SimpleConnectionPool
from datetime import datetime
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()


class DatabaseManager:
    def __init__(self):
        self.host = os.getenv("DB_HOST", "localhost")
        self.port = os.getenv("DB_PORT", "5432")
        self.dbname = os.getenv("DB_NAME", "trading_bot")
        self.user = os.getenv("DB_USER", "trading_user")
        self.password = os.getenv("DB_PASSWORD", "trading_password")
        self._log_hooks = []

        # Connection pool: min 2, max 10 connections
        self._pool = None
        self._init_pool()

        self.init_db()

    def _init_pool(self):
        """Inicializa el pool de conexiones a PostgreSQL."""
        try:
            self._pool = SimpleConnectionPool(
                minconn=2,
                maxconn=10,
                host=self.host,
                port=self.port,
                dbname=self.dbname,
                user=self.user,
                password=self.password,
            )
            print("[DB] Pool de conexiones inicializado.")
        except Exception as e:
            print(f"[DB] Error al crear pool de conexiones: {e}")
            self._pool = None

    def add_log_hook(self, hook):
        """Registra un callback para transmitir logs en tiempo real.

        El callback recibe: (level, message, worker_id, timestamp)
        Se llama sincrónicamente después de cada inserción exitosa en logs.
        """
        self._log_hooks.append(hook)

    def _get_connection(self):
        """Retorna una conexión del pool (o crea una nueva si el pool falló)."""
        if self._pool:
            return self._pool.getconn()
        return psycopg2.connect(
            host=self.host,
            port=self.port,
            dbname=self.dbname,
            user=self.user,
            password=self.password,
        )

    def _return_connection(self, conn):
        """Devuelve una conexión al pool."""
        if self._pool and conn:
            self._pool.putconn(conn)

    def init_db(self):
        """Inicializa las tablas en PostgreSQL para el bot de trading."""
        queries = [
            # Tabla de estado global del bot
            """
            CREATE TABLE IF NOT EXISTS bot_state (
                key VARCHAR(100) PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """,
            # Tabla de transacciones (trades)
            """
            CREATE TABLE IF NOT EXISTS trades (
                id SERIAL PRIMARY KEY,
                timestamp TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                symbol VARCHAR(100) NOT NULL,
                side VARCHAR(10) NOT NULL,       -- 'BUY' o 'SELL'
                price NUMERIC(18, 8) NOT NULL,
                amount NUMERIC(18, 8) NOT NULL,
                total NUMERIC(18, 8) NOT NULL,
                status VARCHAR(100) NOT NULL,     -- 'PENDING', 'COMPLETED', 'FAILED'
                external_order_id VARCHAR(100),
                worker_id VARCHAR(50) NOT NULL DEFAULT 'worker_1'
            );
            """,
            # Tabla de logs persistentes
            """
            CREATE TABLE IF NOT EXISTS logs (
                id SERIAL PRIMARY KEY,
                timestamp TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                level VARCHAR(10) NOT NULL,       -- 'INFO', 'WARNING', 'ERROR'
                message TEXT NOT NULL,
                worker_id VARCHAR(50) NOT NULL DEFAULT 'system'
            );
            """,
            # Tabla de estado del portafolio (balance virtual o real)
            """
            CREATE TABLE IF NOT EXISTS portfolio_state (
                id SERIAL PRIMARY KEY,
                timestamp TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                asset VARCHAR(100) NOT NULL,
                free_balance NUMERIC(18, 8) NOT NULL,
                locked_balance NUMERIC(18, 8) NOT NULL DEFAULT 0.0,
                worker_id VARCHAR(50) NOT NULL DEFAULT 'worker_1'
            );
            """,
            # Tabla de posiciones abiertas (persistencia de estado del strategy)
            """
            CREATE TABLE IF NOT EXISTS positions (
                id SERIAL PRIMARY KEY,
                worker_id VARCHAR(50) NOT NULL DEFAULT 'worker_1',
                symbol VARCHAR(100) NOT NULL,
                side VARCHAR(10) NOT NULL,
                entry_price NUMERIC(18, 8) NOT NULL,
                entry_lead_price NUMERIC(18, 8) NOT NULL DEFAULT 0.0,
                amount NUMERIC(18, 8) NOT NULL DEFAULT 1.0,
                entry_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                status VARCHAR(20) NOT NULL DEFAULT 'OPEN',
                close_price NUMERIC(18, 8),
                close_time TIMESTAMP,
                close_reason TEXT,
                pnl NUMERIC(18, 8),
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """,
            # Migraciones para asegurar la longitud de las columnas
            "ALTER TABLE trades ALTER COLUMN symbol TYPE VARCHAR(100);",
            "ALTER TABLE portfolio_state ALTER COLUMN asset TYPE VARCHAR(100);",
            "ALTER TABLE portfolio_state ADD COLUMN IF NOT EXISTS worker_id VARCHAR(50) NOT NULL DEFAULT 'worker_1';",
            "ALTER TABLE trades ADD COLUMN IF NOT EXISTS position_id INTEGER;",
            # Audit trail columns
            "ALTER TABLE trades ADD COLUMN IF NOT EXISTS trading_mode VARCHAR(20) NOT NULL DEFAULT 'paper';",
            "ALTER TABLE trades ADD COLUMN IF NOT EXISTS fees NUMERIC(18, 8) NOT NULL DEFAULT 0.0;",
            "ALTER TABLE positions ADD COLUMN IF NOT EXISTS trading_mode VARCHAR(20) NOT NULL DEFAULT 'paper';",
            "ALTER TABLE positions ADD COLUMN IF NOT EXISTS fees NUMERIC(18, 8) NOT NULL DEFAULT 0.0;",
            "ALTER TABLE positions ADD COLUMN IF NOT EXISTS duration_seconds NUMERIC(12, 2);",
        ]

        conn = None
        try:
            conn = self._get_connection()
            with conn.cursor() as cursor:
                for query in queries:
                    cursor.execute(query)
                conn.commit()
            self.log("INFO", "Base de datos PostgreSQL inicializada con éxito.")
        except Exception as e:
            print(f"[Error de DB] No se pudo inicializar la base de datos: {e}")
            if conn:
                conn.rollback()
            raise e
        finally:
            self._return_connection(conn)

    def set_state(self, key: str, value: str):
        """Inserta o actualiza una variable de estado en bot_state."""
        query = """
        INSERT INTO bot_state (key, value, updated_at)
        VALUES (%s, %s, %s)
        ON CONFLICT (key) 
        DO UPDATE SET value = EXCLUDED.value, updated_at = EXCLUDED.updated_at;
        """
        now = datetime.now()
        conn = None
        try:
            conn = self._get_connection()
            with conn.cursor() as cursor:
                cursor.execute(query, (key, str(value), now))
                conn.commit()
        except Exception as e:
            self.log("ERROR", f"Error al guardar estado '{key}': {e}")
            if conn:
                conn.rollback()
        finally:
            self._return_connection(conn)

    def get_state(self, key: str, default=None) -> str:
        """Obtiene un valor de estado guardado."""
        query = "SELECT value FROM bot_state WHERE key = %s;"
        conn = None
        try:
            conn = self._get_connection()
            with conn.cursor() as cursor:
                cursor.execute(query, (key,))
                row = cursor.fetchone()
                return row[0] if row else default
        except Exception as e:
            print(f"[Error de DB] Error al leer estado '{key}': {e}")
            return default
        finally:
            self._return_connection(conn)

    def log(self, level: str, message: str, worker_id: str = "system"):
        """Guarda un log en la consola y en PostgreSQL."""
        now = datetime.now()
        print(f"[{now.isoformat()}] {level} ({worker_id}): {message}")
        query = """
        INSERT INTO logs (timestamp, level, message, worker_id)
        VALUES (%s, %s, %s, %s);
        """
        conn = None
        try:
            conn = self._get_connection()
            with conn.cursor() as cursor:
                cursor.execute(query, (now, level, message, worker_id))
                conn.commit()
            # Notificar hooks de log en tiempo real (no deben lanzar excepciones)
            for hook in self._log_hooks:
                try:
                    hook(level, message, worker_id, now)
                except Exception:
                    pass
        except Exception as e:
            print(f"[Error de Logs] No se pudo guardar log en DB: {e}")
            if conn:
                conn.rollback()
        finally:
            self._return_connection(conn)

    def save_trade(
        self,
        symbol: str,
        side: str,
        price: float,
        amount: float,
        external_order_id: str = None,
        status: str = "COMPLETED",
        worker_id: str = "worker_1",
        position_id: int = None,
        trading_mode: str = "paper",
        fees: float = 0.0,
    ) -> int:
        """Guarda un registro de trade en la base de datos."""
        query = """
        INSERT INTO trades (timestamp, symbol, side, price, amount, total, status, external_order_id, worker_id, position_id, trading_mode, fees)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id;
        """
        now = datetime.now()
        total = price * amount
        conn = None
        try:
            conn = self._get_connection()
            with conn.cursor() as cursor:
                cursor.execute(
                    query,
                    (
                        now,
                        symbol,
                        side.upper(),
                        price,
                        amount,
                        total,
                        status,
                        external_order_id,
                        worker_id,
                        position_id,
                        trading_mode,
                        fees,
                    ),
                )
                trade_id = cursor.fetchone()[0]
                conn.commit()
                self.log(
                    "INFO",
                    f"Trade guardado - {side.upper()} {amount} {symbol} @ {price} [{trading_mode}]",
                    worker_id,
                )
                return trade_id
        except Exception as e:
            self.log("ERROR", f"Error al guardar trade: {e}", worker_id)
            if conn:
                conn.rollback()
            return -1
        finally:
            self._return_connection(conn)

    def get_trades(self, limit=50, worker_id: str = None):
        """Obtiene el historial de transacciones."""
        if worker_id:
            query = "SELECT * FROM trades WHERE worker_id = %s ORDER BY timestamp DESC LIMIT %s;"
            args = (worker_id, limit)
        else:
            query = "SELECT * FROM trades ORDER BY timestamp DESC LIMIT %s;"
            args = (limit,)
        conn = None
        try:
            conn = self._get_connection()
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(query, args)
                return cursor.fetchall()
        except Exception as e:
            self.log("ERROR", f"Error al recuperar trades: {e}")
            return []
        finally:
            self._return_connection(conn)

    def get_pending_trades(self, worker_id: str = None):
        """Obtiene todos los trades pendientes (PENDING_NEW, NEW, ACCEPTED)."""
        if worker_id:
            query = "SELECT * FROM trades WHERE worker_id = %s AND status IN ('PENDING_NEW', 'NEW', 'ACCEPTED') ORDER BY timestamp DESC;"
            args = (worker_id,)
        else:
            query = "SELECT * FROM trades WHERE status IN ('PENDING_NEW', 'NEW', 'ACCEPTED') ORDER BY timestamp DESC;"
            args = ()
        conn = None
        try:
            conn = self._get_connection()
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(query, args)
                return cursor.fetchall()
        except Exception as e:
            self.log("ERROR", f"Error al recuperar trades pendientes: {e}")
            return []
        finally:
            self._return_connection(conn)

    def update_trade_status(self, external_order_id: str, status: str):
        """Actualiza el estado de una orden por su id externo o id local."""
        is_numeric = False
        try:
            int(external_order_id)
            is_numeric = True
        except (ValueError, TypeError):
            pass

        if is_numeric:
            query = "UPDATE trades SET status = %s WHERE id = %s;"
            args = (status.upper(), int(external_order_id))
        else:
            query = "UPDATE trades SET status = %s WHERE external_order_id = %s;"
            args = (status.upper(), external_order_id)

        conn = None
        try:
            conn = self._get_connection()
            with conn.cursor() as cursor:
                cursor.execute(query, args)
                conn.commit()
        except Exception as e:
            self.log(
                "ERROR",
                f"Error al actualizar estado del trade {external_order_id} a {status}: {e}",
            )
            if conn:
                conn.rollback()
        finally:
            self._return_connection(conn)

    def get_logs(self, limit=50, worker_id: str = None):
        """Obtiene el historial de logs de auditoría."""
        if worker_id:
            query = "SELECT * FROM logs WHERE worker_id = %s ORDER BY timestamp DESC LIMIT %s;"
            args = (worker_id, limit)
        else:
            query = "SELECT * FROM logs ORDER BY timestamp DESC LIMIT %s;"
            args = (limit,)
        conn = None
        try:
            conn = self._get_connection()
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(query, args)
                return cursor.fetchall()
        except Exception as e:
            print(f"[Error de DB] Error al recuperar logs: {e}")
            return []
        finally:
            self._return_connection(conn)

    def update_portfolio(
        self,
        asset: str,
        free_balance: float,
        locked_balance: float = 0.0,
        worker_id: str = "worker_1",
    ):
        """Inserta o actualiza el balance de un activo en el portafolio."""
        query = """
        INSERT INTO portfolio_state (timestamp, asset, free_balance, locked_balance, worker_id)
        VALUES (%s, %s, %s, %s, %s);
        """
        now = datetime.now()
        conn = None
        try:
            conn = self._get_connection()
            with conn.cursor() as cursor:
                cursor.execute(
                    query, (now, asset.upper(), free_balance, locked_balance, worker_id)
                )
                conn.commit()
        except Exception as e:
            self.log(
                "ERROR",
                f"Error al actualizar portafolio para '{asset}' en {worker_id}: {e}",
            )
            if conn:
                conn.rollback()
        finally:
            self._return_connection(conn)

    def get_portfolio(self, worker_id: str = "worker_1"):
        """Obtiene el estado más reciente de cada activo en el portafolio para un worker específico."""
        query = """
        SELECT DISTINCT ON (asset) asset, free_balance, locked_balance, timestamp
        FROM portfolio_state
        WHERE worker_id = %s
        ORDER BY asset, timestamp DESC;
        """
        conn = None
        try:
            conn = self._get_connection()
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(query, (worker_id,))
                return cursor.fetchall()
        except Exception as e:
            self.log(
                "ERROR",
                f"Error al recuperar portafolio para {worker_id}: {e}",
                worker_id,
            )
            return []
        finally:
            self._return_connection(conn)

    def get_total_equity_usd(self) -> float:
        """Compute total portfolio equity across all workers in USD.

        Non-USD assets are valued using their last known trade price.
        USD assets contribute their free_balance directly.
        """
        conn = None
        try:
            conn = self._get_connection()
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT worker_id, asset, free_balance::float
                    FROM (
                        SELECT DISTINCT ON (worker_id, asset)
                               worker_id, asset, free_balance
                        FROM portfolio_state
                        ORDER BY worker_id, asset, timestamp DESC
                    ) latest
                """)
                rows = cur.fetchall()

                total = 0.0
                non_usd = []
                for worker_id, asset, balance in rows:
                    if asset == "USD":
                        total += balance
                    else:
                        non_usd.append((worker_id, asset, balance))

                if non_usd:
                    cur.execute("""
                        SELECT DISTINCT ON (symbol) symbol, price::float
                        FROM trades
                        ORDER BY symbol, timestamp DESC
                    """)
                    last_prices = {row[0]: row[1] for row in cur.fetchall()}

                    for _wid, asset, balance in non_usd:
                        price = 0.0
                        for sym, p in last_prices.items():
                            if asset in sym:
                                price = p
                                break
                        total += balance * price

            return total
        except Exception:
            return 0.0
        finally:
            self._return_connection(conn)

    def save_position(
        self,
        worker_id: str,
        symbol: str,
        side: str,
        entry_price: float,
        entry_lead_price: float = 0.0,
        amount: float = 1.0,
    ) -> int:
        """Guarda una posición abierta. Retorna el ID de la posición."""
        query = """
        INSERT INTO positions (worker_id, symbol, side, entry_price, entry_lead_price, amount, entry_time, status)
        VALUES (%s, %s, %s, %s, %s, %s, %s, 'OPEN') RETURNING id;
        """
        now = datetime.now()
        conn = None
        try:
            conn = self._get_connection()
            with conn.cursor() as cursor:
                cursor.execute(
                    query,
                    (worker_id, symbol, side, entry_price, entry_lead_price, amount, now),
                )
                pos_id = cursor.fetchone()[0]
                conn.commit()
                self.log(
                    "INFO",
                    f"Posición abierta guardada: {side} {amount} {symbol} @ {entry_price} (ID: {pos_id})",
                    worker_id,
                )
                return pos_id
        except Exception as e:
            self.log("ERROR", f"Error al guardar posición: {e}", worker_id)
            if conn:
                conn.rollback()
            return -1
        finally:
            self._return_connection(conn)

    def close_position(
        self,
        position_id: int,
        close_price: float,
        close_reason: str,
        worker_id: str = "worker_1",
        fees: float = 0.0,
    ):
        """Cierra una posición abierta y calcula P&L."""
        query = """
        UPDATE positions
        SET status = 'CLOSED', close_price = %s, close_time = %s, close_reason = %s,
            fees = %s,
            duration_seconds = EXTRACT(EPOCH FROM (%s - entry_time)),
            pnl = CASE
                WHEN side = 'BUY' THEN (%s - entry_price) * amount - %s
                WHEN side = 'SELL' THEN (entry_price - %s) * amount - %s
                ELSE 0
            END
        WHERE id = %s AND status = 'OPEN';
        """
        now = datetime.now()
        conn = None
        try:
            conn = self._get_connection()
            with conn.cursor() as cursor:
                cursor.execute(
                    query, (close_price, now, close_reason, fees, now, close_price, fees, close_price, fees, position_id)
                )
                conn.commit()
                self.log(
                    "INFO",
                    f"Posición #{position_id} cerrada: {close_reason} @ {close_price}",
                    worker_id,
                )
        except Exception as e:
            self.log("ERROR", f"Error al cerrar posición #{position_id}: {e}", worker_id)
            if conn:
                conn.rollback()
        finally:
            self._return_connection(conn)

    def get_open_positions(self, worker_id: str = None):
        """Obtiene todas las posiciones abiertas."""
        if worker_id:
            query = "SELECT * FROM positions WHERE worker_id = %s AND status = 'OPEN' ORDER BY entry_time DESC;"
            args = (worker_id,)
        else:
            query = "SELECT * FROM positions WHERE status = 'OPEN' ORDER BY entry_time DESC;"
            args = ()
        conn = None
        try:
            conn = self._get_connection()
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(query, args)
                return cursor.fetchall()
        except Exception as e:
            self.log("ERROR", f"Error al recuperar posiciones abiertas: {e}")
            return []
        finally:
            self._return_connection(conn)

    def get_position_history(self, limit=50, worker_id: str = None):
        """Obtiene el historial de posiciones cerradas."""
        if worker_id:
            query = "SELECT * FROM positions WHERE worker_id = %s AND status = 'CLOSED' ORDER BY close_time DESC LIMIT %s;"
            args = (worker_id, limit)
        else:
            query = "SELECT * FROM positions WHERE status = 'CLOSED' ORDER BY close_time DESC LIMIT %s;"
            args = (limit,)
        conn = None
        try:
            conn = self._get_connection()
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(query, args)
                return cursor.fetchall()
        except Exception as e:
            self.log("ERROR", f"Error al recuperar historial de posiciones: {e}")
            return []
        finally:
            self._return_connection(conn)

    def get_all_positions(self, limit=50, worker_id: str = None):
        """Obtiene todas las posiciones (abiertas + cerradas)."""
        if worker_id:
            query = "SELECT * FROM positions WHERE worker_id = %s ORDER BY created_at DESC LIMIT %s;"
            args = (worker_id, limit)
        else:
            query = "SELECT * FROM positions ORDER BY created_at DESC LIMIT %s;"
            args = (limit,)
        conn = None
        try:
            conn = self._get_connection()
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(query, args)
                return cursor.fetchall()
        except Exception as e:
            self.log("ERROR", f"Error al recuperar posiciones: {e}")
            return []
        finally:
            self._return_connection(conn)

    def get_open_position_by_worker(self, worker_id: str):
        """Obtiene la posición abierta más reciente de un worker."""
        query = "SELECT * FROM positions WHERE worker_id = %s AND status = 'OPEN' ORDER BY entry_time DESC LIMIT 1;"
        conn = None
        try:
            conn = self._get_connection()
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(query, (worker_id,))
                return cursor.fetchone()
        except Exception as e:
            self.log("ERROR", f"Error al recuperar posición abierta para {worker_id}: {e}")
            return None
        finally:
            self._return_connection(conn)

    # ==================================================================
    # AUDIT TRAIL & P&L SUMMARY
    # ==================================================================

    def get_pnl_summary(
        self,
        worker_id: str = None,
        trading_mode: str = None,
        start_date: str = None,
        end_date: str = None,
    ) -> dict:
        """
        Returns aggregated P&L metrics for closed positions.
        Filters: worker_id, trading_mode (paper/real), date range.
        """
        conditions = ["status = 'CLOSED'"]
        params = []

        if worker_id:
            conditions.append("worker_id = %s")
            params.append(worker_id)
        if trading_mode:
            conditions.append("trading_mode = %s")
            params.append(trading_mode)
        if start_date:
            conditions.append("close_time >= %s")
            params.append(start_date)
        if end_date:
            conditions.append("close_time <= %s")
            params.append(end_date)

        where = " AND ".join(conditions)
        query = f"""
        SELECT
            COUNT(*) as total_trades,
            COUNT(*) FILTER (WHERE pnl > 0) as winning_trades,
            COUNT(*) FILTER (WHERE pnl <= 0) as losing_trades,
            COALESCE(SUM(pnl), 0) as total_pnl,
            COALESCE(AVG(pnl), 0) as avg_pnl,
            COALESCE(MAX(pnl), 0) as best_trade,
            COALESCE(MIN(pnl), 0) as worst_trade,
            COALESCE(SUM(fees), 0) as total_fees,
            COALESCE(AVG(duration_seconds), 0) as avg_duration_sec,
            COALESCE(SUM(pnl) FILTER (WHERE pnl > 0), 0) as gross_profit,
            COALESCE(ABS(SUM(pnl) FILTER (WHERE pnl <= 0)), 0) as gross_loss
        FROM positions
        WHERE {where};
        """

        conn = None
        try:
            conn = self._get_connection()
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(query, params)
                row = cursor.fetchone()

            if not row or row["total_trades"] == 0:
                return self._empty_pnl_summary()

            total = int(row["total_trades"])
            winners = int(row["winning_trades"])
            losers = int(row["losing_trades"])
            gross_profit = float(row["gross_profit"])
            gross_loss = float(row["gross_loss"])

            win_rate = (winners / total * 100) if total > 0 else 0
            profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else float("inf") if gross_profit > 0 else 0
            avg_win = (gross_profit / winners) if winners > 0 else 0
            avg_loss = (gross_loss / losers) if losers > 0 else 0
            expectancy = (avg_win * win_rate / 100) - (avg_loss * (1 - win_rate / 100))

            return {
                "total_trades": total,
                "winning_trades": winners,
                "losing_trades": losers,
                "win_rate_pct": round(win_rate, 2),
                "total_pnl": round(float(row["total_pnl"]), 4),
                "avg_pnl": round(float(row["avg_pnl"]), 4),
                "best_trade": round(float(row["best_trade"]), 4),
                "worst_trade": round(float(row["worst_trade"]), 4),
                "gross_profit": round(gross_profit, 4),
                "gross_loss": round(gross_loss, 4),
                "profit_factor": round(profit_factor, 4),
                "expectancy": round(expectancy, 4),
                "avg_win": round(avg_win, 4),
                "avg_loss": round(avg_loss, 4),
                "total_fees": round(float(row["total_fees"]), 4),
                "avg_duration_sec": round(float(row["avg_duration_sec"]), 1),
            }
        except Exception as e:
            self.log("ERROR", f"Error computing P&L summary: {e}")
            return self._empty_pnl_summary()
        finally:
            self._return_connection(conn)

    def _empty_pnl_summary(self) -> dict:
        return {
            "total_trades": 0,
            "winning_trades": 0,
            "losing_trades": 0,
            "win_rate_pct": 0,
            "total_pnl": 0,
            "avg_pnl": 0,
            "best_trade": 0,
            "worst_trade": 0,
            "gross_profit": 0,
            "gross_loss": 0,
            "profit_factor": 0,
            "expectancy": 0,
            "avg_win": 0,
            "avg_loss": 0,
            "total_fees": 0,
            "avg_duration_sec": 0,
        }

    def get_equity_curve(
        self,
        worker_id: str = None,
        start_date: str = None,
        end_date: str = None,
    ) -> list[dict]:
        """
        Returns portfolio balance time series from portfolio_state.
        Used for equity curve charting.
        """
        conditions = []
        params = []

        if worker_id:
            conditions.append("worker_id = %s")
            params.append(worker_id)
        if start_date:
            conditions.append("timestamp >= %s")
            params.append(start_date)
        if end_date:
            conditions.append("timestamp <= %s")
            params.append(end_date)

        where = (" WHERE " + " AND ".join(conditions)) if conditions else ""

        query = f"""
        SELECT
            timestamp,
            SUM(free_balance + locked_balance) as total_equity,
            worker_id
        FROM portfolio_state
        {where}
        GROUP BY timestamp, worker_id
        ORDER BY timestamp ASC;
        """

        conn = None
        try:
            conn = self._get_connection()
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(query, params)
                rows = cursor.fetchall()
            return [
                {
                    "timestamp": r["timestamp"].isoformat() if r["timestamp"] else None,
                    "equity": round(float(r["total_equity"]), 4),
                    "worker_id": r["worker_id"],
                }
                for r in rows
            ]
        except Exception as e:
            self.log("ERROR", f"Error fetching equity curve: {e}")
            return []
        finally:
            self._return_connection(conn)

    def get_trades_export(
        self,
        worker_id: str = None,
        trading_mode: str = None,
        start_date: str = None,
        end_date: str = None,
        limit: int = 10000,
    ) -> list[dict]:
        """
        Returns trades + positions joined for CSV export.
        Includes all audit fields.
        """
        conditions = []
        params = []

        if worker_id:
            conditions.append("t.worker_id = %s")
            params.append(worker_id)
        if trading_mode:
            conditions.append("t.trading_mode = %s")
            params.append(trading_mode)
        if start_date:
            conditions.append("t.timestamp >= %s")
            params.append(start_date)
        if end_date:
            conditions.append("t.timestamp <= %s")
            params.append(end_date)

        where = (" WHERE " + " AND ".join(conditions)) if conditions else ""

        query = f"""
        SELECT
            t.id as trade_id,
            t.timestamp,
            t.symbol,
            t.side,
            t.price,
            t.amount,
            t.total,
            t.fees,
            t.status,
            t.trading_mode,
            t.worker_id,
            t.position_id,
            t.external_order_id,
            p.entry_price,
            p.close_price,
            p.pnl,
            p.close_reason,
            p.duration_seconds
        FROM trades t
        LEFT JOIN positions p ON t.position_id = p.id
        {where}
        ORDER BY t.timestamp DESC
        LIMIT {limit};
        """

        conn = None
        try:
            conn = self._get_connection()
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(query, params)
                rows = cursor.fetchall()
            return [
                {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in r.items()}
                for r in rows
            ]
        except Exception as e:
            self.log("ERROR", f"Error exporting trades: {e}")
            return []
        finally:
            self._return_connection(conn)
