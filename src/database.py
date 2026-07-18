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
    ) -> int:
        """Guarda un registro de trade en la base de datos."""
        query = """
        INSERT INTO trades (timestamp, symbol, side, price, amount, total, status, external_order_id, worker_id, position_id)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id;
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
                    ),
                )
                trade_id = cursor.fetchone()[0]
                conn.commit()
                self.log(
                    "INFO",
                    f"Trade guardado - {side.upper()} {amount} {symbol} @ {price}",
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
    ):
        """Cierra una posición abierta y calcula P&L."""
        query = """
        UPDATE positions
        SET status = 'CLOSED', close_price = %s, close_time = %s, close_reason = %s,
            pnl = CASE
                WHEN side = 'BUY' THEN (%s - entry_price) * amount
                WHEN side = 'SELL' THEN (entry_price - %s) * amount
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
                    query, (close_price, now, close_reason, close_price, close_price, position_id)
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
