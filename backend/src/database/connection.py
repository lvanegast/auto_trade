import os
import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2.pool import SimpleConnectionPool
from dotenv import load_dotenv

load_dotenv()


class DatabaseManager:
    """Administrador central del pool de conexiones PostgreSQL y migraciones de esquema."""

    def __init__(self):
        self.host = os.getenv("DB_HOST", "localhost")
        self.port = os.getenv("DB_PORT", "5432")
        self.dbname = os.getenv("DB_NAME", "trading_bot")
        self.user = os.getenv("DB_USER", "trading_user")
        self.password = os.getenv("DB_PASSWORD", "trading_password")
        self._log_hooks = []

        self._pool = None
        self._init_pool()
        self.init_db()

    def _init_pool(self):
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
            print("[DB] Pool de conexiones PostgreSQL inicializado.")
        except Exception as e:
            print(f"[DB] Error al crear pool de conexiones: {e}")
            self._pool = None

    def add_log_hook(self, hook):
        self._log_hooks.append(hook)

    def _get_connection(self):
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
        if self._pool and conn:
            self._pool.putconn(conn)

    def init_db(self):
        queries = [
            """
            CREATE TABLE IF NOT EXISTS bot_state (
                key VARCHAR(100) PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS trades (
                id SERIAL PRIMARY KEY,
                timestamp TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                symbol VARCHAR(100) NOT NULL,
                side VARCHAR(10) NOT NULL,
                price NUMERIC(18, 8) NOT NULL,
                amount NUMERIC(18, 8) NOT NULL,
                total NUMERIC(18, 8) NOT NULL,
                status VARCHAR(100) NOT NULL,
                external_order_id VARCHAR(100),
                worker_id VARCHAR(50) NOT NULL DEFAULT 'worker_1'
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS logs (
                id SERIAL PRIMARY KEY,
                timestamp TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                level VARCHAR(10) NOT NULL,
                message TEXT NOT NULL,
                worker_id VARCHAR(50) NOT NULL DEFAULT 'system'
            );
            """,
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
            """
            CREATE TABLE IF NOT EXISTS positions (
                id SERIAL PRIMARY KEY,
                worker_id VARCHAR(50) NOT NULL DEFAULT 'worker_1',
                symbol VARCHAR(100) NOT NULL,
                side VARCHAR(10) NOT NULL,
                entry_price NUMERIC(18, 8) NOT NULL,
                entry_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                status VARCHAR(20) NOT NULL DEFAULT 'OPEN',
                exit_price NUMERIC(18, 8),
                exit_time TIMESTAMP,
                exit_reason VARCHAR(100),
                pnl NUMERIC(18, 8),
                pnl_pct NUMERIC(10, 4),
                entry_lead_price NUMERIC(18, 8),
                exit_lead_price NUMERIC(18, 8),
                amount NUMERIC(18, 8),
                stop_loss_price NUMERIC(18, 8),
                take_profit_price NUMERIC(18, 8),
                highest_price_seen NUMERIC(18, 8)
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username VARCHAR(50) UNIQUE NOT NULL,
                password_hash VARCHAR(255) NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """,
        ]

        migrations = [
            "ALTER TABLE trades ADD COLUMN IF NOT EXISTS worker_id VARCHAR(50) NOT NULL DEFAULT 'worker_1';",
            "ALTER TABLE portfolio_state ADD COLUMN IF NOT EXISTS worker_id VARCHAR(50) NOT NULL DEFAULT 'worker_1';",
            "ALTER TABLE positions ADD COLUMN IF NOT EXISTS entry_lead_price NUMERIC(18, 8);",
            "ALTER TABLE positions ADD COLUMN IF NOT EXISTS exit_lead_price NUMERIC(18, 8);",
            "ALTER TABLE positions ADD COLUMN IF NOT EXISTS amount NUMERIC(18, 8);",
            "ALTER TABLE positions ADD COLUMN IF NOT EXISTS stop_loss_price NUMERIC(18, 8);",
            "ALTER TABLE positions ADD COLUMN IF NOT EXISTS take_profit_price NUMERIC(18, 8);",
            "ALTER TABLE positions ADD COLUMN IF NOT EXISTS highest_price_seen NUMERIC(18, 8);",
            "ALTER TABLE trades ADD COLUMN IF NOT EXISTS position_id INTEGER REFERENCES positions(id);",
            "ALTER TABLE portfolio_state ALTER COLUMN asset TYPE VARCHAR(100);",
            "ALTER TABLE positions ALTER COLUMN symbol TYPE VARCHAR(100);",
            "ALTER TABLE trades ALTER COLUMN symbol TYPE VARCHAR(100);",
        ]

        conn = None
        try:
            conn = self._get_connection()
            with conn.cursor() as cursor:
                for q in queries:
                    cursor.execute(q)
                for m in migrations:
                    try:
                        cursor.execute(m)
                    except Exception:
                        conn.rollback()
                        conn = self._get_connection()
                conn.commit()
                print("[DB] Base de datos PostgreSQL inicializada con éxito.")
        except Exception as e:
            print(f"[DB] Error crítico inicializando base de datos: {e}")
            if conn:
                conn.rollback()
        finally:
            self._return_connection(conn)

    # Proxy methods for backward compatibility
    def set_state(self, key: str, value: str):
        query = """
        INSERT INTO bot_state (key, value, updated_at)
        VALUES (%s, %s, CURRENT_TIMESTAMP)
        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = CURRENT_TIMESTAMP;
        """
        conn = None
        try:
            conn = self._get_connection()
            with conn.cursor() as cursor:
                cursor.execute(query, (key, value))
                conn.commit()
        finally:
            self._return_connection(conn)

    def get_state(self, key: str, default: str = None) -> str:
        query = "SELECT value FROM bot_state WHERE key = %s;"
        conn = None
        try:
            conn = self._get_connection()
            with conn.cursor() as cursor:
                cursor.execute(query, (key,))
                row = cursor.fetchone()
                return row[0] if row else default
        finally:
            self._return_connection(conn)

    def log(self, level: str, message: str, worker_id: str = "system"):
        query = "INSERT INTO logs (level, message, worker_id) VALUES (%s, %s, %s) RETURNING timestamp;"
        conn = None
        try:
            conn = self._get_connection()
            with conn.cursor() as cursor:
                cursor.execute(query, (level, message, worker_id))
                ts = cursor.fetchone()[0]
                conn.commit()

            for hook in self._log_hooks:
                try:
                    hook(level, message, worker_id, ts)
                except Exception as ex:
                    print(f"[DB] Error en log hook: {ex}")
        finally:
            self._return_connection(conn)

    def get_logs(self, limit: int = 100, worker_id: str = None):
        if worker_id:
            query = "SELECT * FROM logs WHERE worker_id = %s ORDER BY timestamp DESC LIMIT %s;"
            params = (worker_id, limit)
        else:
            query = "SELECT * FROM logs ORDER BY timestamp DESC LIMIT %s;"
            params = (limit,)
        conn = None
        try:
            conn = self._get_connection()
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(query, params)
                return cursor.fetchall()
        finally:
            self._return_connection(conn)

    def get_portfolio(self, worker_id: str = "worker_1"):
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
        finally:
            self._return_connection(conn)

    def update_portfolio(
        self,
        asset: str,
        free_balance: float,
        locked_balance: float = 0.0,
        worker_id: str = "worker_1",
    ):
        query = """
        INSERT INTO portfolio_state (timestamp, asset, free_balance, locked_balance, worker_id)
        VALUES (CURRENT_TIMESTAMP, %s, %s, %s, %s);
        """
        conn = None
        try:
            conn = self._get_connection()
            with conn.cursor() as cursor:
                cursor.execute(
                    query, (asset.upper(), free_balance, locked_balance, worker_id)
                )
                conn.commit()
        finally:
            self._return_connection(conn)

    def save_trade(
        self,
        symbol: str,
        side: str,
        price: float,
        amount: float,
        total: float,
        status: str = "COMPLETED",
        external_order_id: str = None,
        worker_id: str = "worker_1",
        position_id: int = None,
    ):
        query = """
        INSERT INTO trades (symbol, side, price, amount, total, status, external_order_id, worker_id, position_id)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id;
        """
        conn = None
        try:
            conn = self._get_connection()
            with conn.cursor() as cursor:
                cursor.execute(
                    query,
                    (
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
                return trade_id
        finally:
            self._return_connection(conn)

    def get_trades(self, limit: int = 50, worker_id: str = None):
        if worker_id:
            query = "SELECT * FROM trades WHERE worker_id = %s ORDER BY timestamp DESC LIMIT %s;"
            params = (worker_id, limit)
        else:
            query = "SELECT * FROM trades ORDER BY timestamp DESC LIMIT %s;"
            params = (limit,)
        conn = None
        try:
            conn = self._get_connection()
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(query, params)
                return cursor.fetchall()
        finally:
            self._return_connection(conn)

    def save_open_position(
        self,
        worker_id: str,
        symbol: str,
        side: str,
        entry_price: float,
        entry_lead_price: float = None,
        amount: float = None,
        stop_loss_price: float = None,
        take_profit_price: float = None,
    ) -> int:
        query = """
        INSERT INTO positions (worker_id, symbol, side, entry_price, status, entry_lead_price, amount, stop_loss_price, take_profit_price, highest_price_seen)
        VALUES (%s, %s, %s, %s, 'OPEN', %s, %s, %s, %s, %s)
        RETURNING id;
        """
        highest = entry_price
        conn = None
        try:
            conn = self._get_connection()
            with conn.cursor() as cursor:
                cursor.execute(
                    query,
                    (
                        worker_id,
                        symbol,
                        side.upper(),
                        entry_price,
                        entry_lead_price,
                        amount,
                        stop_loss_price,
                        take_profit_price,
                        highest,
                    ),
                )
                pos_id = cursor.fetchone()[0]
                conn.commit()
                return pos_id
        finally:
            self._return_connection(conn)

    def close_position(
        self,
        pos_id: int,
        exit_price: float,
        exit_reason: str = "SIGNAL",
        exit_lead_price: float = None,
        worker_id: str = None,
    ):
        query_get = (
            "SELECT entry_price, side FROM positions WHERE id = %s AND status = 'OPEN';"
        )
        conn = None
        try:
            conn = self._get_connection()
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(query_get, (pos_id,))
                pos = cursor.fetchone()
                if not pos:
                    return None

                entry_price = float(pos["entry_price"])
                side = pos["side"]

                if side == "BUY":
                    pnl = exit_price - entry_price
                    pnl_pct = (pnl / entry_price) * 100.0 if entry_price > 0 else 0.0
                else:
                    pnl = entry_price - exit_price
                    pnl_pct = (pnl / entry_price) * 100.0 if entry_price > 0 else 0.0

                query_close = """
                UPDATE positions
                SET status = 'CLOSED', exit_price = %s, exit_time = CURRENT_TIMESTAMP, exit_reason = %s, pnl = %s, pnl_pct = %s, exit_lead_price = %s
                WHERE id = %s;
                """
                cursor.execute(
                    query_close,
                    (exit_price, exit_reason, pnl, pnl_pct, exit_lead_price, pos_id),
                )
                conn.commit()
                return {"pnl": pnl, "pnl_pct": pnl_pct}
        finally:
            self._return_connection(conn)

    def get_open_positions(self, worker_id: str = None):
        if worker_id:
            query = "SELECT * FROM positions WHERE status = 'OPEN' AND worker_id = %s ORDER BY entry_time DESC;"
            params = (worker_id,)
        else:
            query = "SELECT * FROM positions WHERE status = 'OPEN' ORDER BY entry_time DESC;"
            params = ()
        conn = None
        try:
            conn = self._get_connection()
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(query, params)
                return cursor.fetchall()
        finally:
            self._return_connection(conn)

    def get_open_position_by_worker(self, worker_id: str):
        positions = self.get_open_positions(worker_id=worker_id)
        return positions[0] if positions else None
