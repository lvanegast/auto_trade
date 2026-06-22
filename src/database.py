import os
import psycopg2
from psycopg2.extras import RealDictCursor
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

        self.init_db()

    def _get_connection(self):
        """Retorna una conexión a la base de datos PostgreSQL."""
        return psycopg2.connect(
            host=self.host,
            port=self.port,
            dbname=self.dbname,
            user=self.user,
            password=self.password,
        )

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
                symbol VARCHAR(20) NOT NULL,
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
                asset VARCHAR(20) NOT NULL,
                free_balance NUMERIC(18, 8) NOT NULL,
                locked_balance NUMERIC(18, 8) NOT NULL DEFAULT 0.0
            );
            """,
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
            if conn:
                conn.close()

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
            if conn:
                conn.close()

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
            if conn:
                conn.close()

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
        except Exception as e:
            print(f"[Error de Logs] No se pudo guardar log en DB: {e}")
            if conn:
                conn.rollback()
        finally:
            if conn:
                conn.close()

    def save_trade(
        self,
        symbol: str,
        side: str,
        price: float,
        amount: float,
        external_order_id: str = None,
        status: str = "COMPLETED",
        worker_id: str = "worker_1",
    ) -> int:
        """Guarda un registro de trade en la base de datos."""
        query = """
        INSERT INTO trades (timestamp, symbol, side, price, amount, total, status, external_order_id, worker_id)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id;
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
            if conn:
                conn.close()

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
            if conn:
                conn.close()

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
            if conn:
                conn.close()

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
            if conn:
                conn.close()

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
            if conn:
                conn.close()

    def update_portfolio(
        self, asset: str, free_balance: float, locked_balance: float = 0.0
    ):
        """Inserta o actualiza el balance de un activo en el portafolio."""
        query = """
        INSERT INTO portfolio_state (timestamp, asset, free_balance, locked_balance)
        VALUES (%s, %s, %s, %s);
        """
        now = datetime.now()
        conn = None
        try:
            conn = self._get_connection()
            with conn.cursor() as cursor:
                cursor.execute(
                    query, (now, asset.upper(), free_balance, locked_balance)
                )
                conn.commit()
        except Exception as e:
            self.log("ERROR", f"Error al actualizar portafolio para '{asset}': {e}")
            if conn:
                conn.rollback()
        finally:
            if conn:
                conn.close()

    def get_portfolio(self):
        """Obtiene el estado más reciente de cada activo en el portafolio."""
        query = """
        SELECT DISTINCT ON (asset) asset, free_balance, locked_balance, timestamp
        FROM portfolio_state
        ORDER BY asset, timestamp DESC;
        """
        conn = None
        try:
            conn = self._get_connection()
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(query)
                return cursor.fetchall()
        except Exception as e:
            self.log("ERROR", f"Error al recuperar portafolio: {e}")
            return []
        finally:
            if conn:
                conn.close()
