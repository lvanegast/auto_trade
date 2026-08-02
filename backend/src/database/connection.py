import os
import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2.pool import SimpleConnectionPool
from dotenv import load_dotenv

# Load .env from project root (parent of backend/)
_load_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
load_dotenv(os.path.join(_load_dir, ".env"), override=True)


import sqlite3

class SQLiteDictCursor:
    def __init__(self, cursor):
        self.cursor = cursor
    def execute(self, query, params=()):
        q = query.replace("%s", "?")
        q = q.replace("SERIAL PRIMARY KEY", "INTEGER PRIMARY KEY AUTOINCREMENT")
        q = q.replace("ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = CURRENT_TIMESTAMP", "ON CONFLICT(key) DO UPDATE SET value=excluded.value")
        q = q.replace("ON CONFLICT (asset, worker_id) DO UPDATE SET free_balance = EXCLUDED.free_balance, locked_balance = EXCLUDED.locked_balance", "ON CONFLICT(asset, worker_id) DO UPDATE SET free_balance=excluded.free_balance")
        q = q.replace("RETURNING timestamp", "")
        q = q.replace("RETURNING id", "")

        if "DISTINCT ON" in q:
            # Adapt PostgreSQL DISTINCT ON (asset) to SQLite GROUP BY asset
            q = "SELECT asset, free_balance, locked_balance, timestamp FROM portfolio_state WHERE worker_id = ? GROUP BY asset HAVING id = MAX(id)"

        if "ADD COLUMN IF NOT EXISTS" in q:
            parts = q.split("ADD COLUMN IF NOT EXISTS")
            tbl = parts[0].replace("ALTER TABLE", "").strip()
            col_def = parts[1].strip()
            col_name = col_def.split()[0]
            try:
                self.cursor.execute(f"SELECT {col_name} FROM {tbl} LIMIT 1")
                return
            except Exception:
                q = f"ALTER TABLE {tbl} ADD COLUMN {col_def}"

        self.cursor.execute(q, params)
    def fetchone(self):
        r = self.cursor.fetchone()
        if r is None:
            return None
        if isinstance(r, sqlite3.Row):
            return dict(r)
        return r
    def fetchall(self):
        rows = self.cursor.fetchall()
        return [dict(r) if isinstance(r, sqlite3.Row) else r for r in rows]
    def __enter__(self):
        return self
    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

class SQLiteConnectionAdapter:
    def __init__(self, db_path):
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
    def cursor(self, cursor_factory=None):
        return SQLiteDictCursor(self.conn.cursor())
    def commit(self):
        self.conn.commit()
    def rollback(self):
        self.conn.rollback()
    def close(self):
        self.conn.close()

class DatabaseManager:
    """Administrador central del pool de conexiones PostgreSQL (con Fallback a SQLite)."""

    def __init__(self):
        self.host = os.getenv("DB_HOST", "localhost")
        self.port = os.getenv("DB_PORT", "5432")
        self.dbname = os.getenv("DB_NAME", "trading_bot")
        self.user = os.getenv("DB_USER", "trading_user")
        self.password = os.getenv("DB_PASSWORD", "trading_password")
        self._log_hooks = []
        self.use_sqlite = False
        self._sqlite_conn = None

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
            print(f"[DB] PostgreSQL no disponible ({e}). Activando fallback local SQLite...")
            self._pool = None
            self.use_sqlite = True
            db_file = os.path.join(_load_dir, "trading_bot_local.db")
            self._sqlite_conn = SQLiteConnectionAdapter(db_file)
            print(f"[DB] Fallback a SQLite activo: {db_file}")

    def add_log_hook(self, hook):
        self._log_hooks.append(hook)

    def _get_connection(self):
        if self.use_sqlite:
            return self._sqlite_conn
        if self._pool:
            return self._pool.getconn()
        try:
            return psycopg2.connect(
                host=self.host,
                port=self.port,
                dbname=self.dbname,
                user=self.user,
                password=self.password,
            )
        except Exception:
            self.use_sqlite = True
            db_file = os.path.join(_load_dir, "trading_bot_local.db")
            self._sqlite_conn = SQLiteConnectionAdapter(db_file)
            return self._sqlite_conn

    def _return_connection(self, conn):
        if self.use_sqlite:
            return
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
                symbol VARCHAR(255) NOT NULL,
                side VARCHAR(10) NOT NULL,
                price NUMERIC(18, 8) NOT NULL,
                amount NUMERIC(18, 8) NOT NULL,
                total NUMERIC(18, 8) NOT NULL,
                status VARCHAR(100) NOT NULL,
                external_order_id VARCHAR(255),
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
                symbol VARCHAR(255) NOT NULL,
                side VARCHAR(10) NOT NULL,
                entry_price NUMERIC(18, 8) NOT NULL,
                entry_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                status VARCHAR(20) NOT NULL DEFAULT 'OPEN',
                exit_price NUMERIC(18, 8),
                exit_time TIMESTAMP,
                exit_reason VARCHAR(500),
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
            "ALTER TABLE positions ADD COLUMN IF NOT EXISTS exit_price NUMERIC(18, 8);",
            "ALTER TABLE positions ADD COLUMN IF NOT EXISTS exit_time TIMESTAMP;",
            "ALTER TABLE positions ADD COLUMN IF NOT EXISTS exit_reason VARCHAR(100);",
            "ALTER TABLE positions ADD COLUMN IF NOT EXISTS pnl NUMERIC(18, 8);",
            "ALTER TABLE positions ADD COLUMN IF NOT EXISTS pnl_pct NUMERIC(10, 4);",
            "ALTER TABLE positions ADD COLUMN IF NOT EXISTS entry_lead_price NUMERIC(18, 8);",
            "ALTER TABLE positions ADD COLUMN IF NOT EXISTS exit_lead_price NUMERIC(18, 8);",
            "ALTER TABLE positions ADD COLUMN IF NOT EXISTS amount NUMERIC(18, 8);",
            "ALTER TABLE positions ADD COLUMN IF NOT EXISTS stop_loss_price NUMERIC(18, 8);",
            "ALTER TABLE positions ADD COLUMN IF NOT EXISTS take_profit_price NUMERIC(18, 8);",
            "ALTER TABLE positions ADD COLUMN IF NOT EXISTS highest_price_seen NUMERIC(18, 8);",
            "ALTER TABLE trades ADD COLUMN IF NOT EXISTS position_id INTEGER REFERENCES positions(id);",
            "ALTER TABLE portfolio_state ALTER COLUMN asset TYPE VARCHAR(255);",
            "ALTER TABLE positions ALTER COLUMN symbol TYPE VARCHAR(255);",
            "ALTER TABLE trades ALTER COLUMN symbol TYPE VARCHAR(255);",
            "ALTER TABLE trades ALTER COLUMN external_order_id TYPE VARCHAR(255);",
            "ALTER TABLE positions ALTER COLUMN entry_lead_price DROP NOT NULL;",
            "ALTER TABLE positions ALTER COLUMN amount DROP NOT NULL;",
            "ALTER TABLE positions ALTER COLUMN exit_reason TYPE VARCHAR(500);",
            "ALTER TABLE trades ADD COLUMN IF NOT EXISTS requested_price NUMERIC(18, 8);",
            "ALTER TABLE trades ADD COLUMN IF NOT EXISTS filled_price NUMERIC(18, 8);",
            "ALTER TABLE trades ADD COLUMN IF NOT EXISTS requested_qty NUMERIC(18, 8);",
            "ALTER TABLE trades ADD COLUMN IF NOT EXISTS filled_qty NUMERIC(18, 8);",
            "ALTER TABLE trades ADD COLUMN IF NOT EXISTS fee_per_asset NUMERIC(18, 8);",
            "ALTER TABLE trades ADD COLUMN IF NOT EXISTS gas_usd NUMERIC(18, 8);",
            "ALTER TABLE trades ADD COLUMN IF NOT EXISTS slippage_usd NUMERIC(18, 8);",
            "ALTER TABLE trades ADD COLUMN IF NOT EXISTS latency_ms NUMERIC(10, 2);",
            "ALTER TABLE trades ADD COLUMN IF NOT EXISTS queue_latency_ms NUMERIC(10, 2);",
            "ALTER TABLE trades ADD COLUMN IF NOT EXISTS strategy_latency_ms NUMERIC(10, 2);",
            "ALTER TABLE trades ADD COLUMN IF NOT EXISTS execution_latency_ms NUMERIC(10, 2);",
            "ALTER TABLE trades ADD COLUMN IF NOT EXISTS net_pnl NUMERIC(18, 8);",
            "ALTER TABLE trades ADD COLUMN IF NOT EXISTS leg_id VARCHAR(20);",
            "ALTER TABLE positions ADD COLUMN IF NOT EXISTS entry_hedge_price NUMERIC(18, 8);",
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
                
                # Cleanup orphan/past positions at startup
                if os.getenv("DATABASE_CLEANUP_STARTUP") == "true":
                    try:
                        import time
                        cursor.execute("SELECT id, symbol, entry_price FROM positions WHERE status = 'OPEN';")
                        open_pos = cursor.fetchall()
                        closed_count = 0
                        for pid, sym, entry_price in open_pos:
                            try:
                                import re
                                # Extract 10-13 digit timestamp anywhere in symbol
                                numbers = re.findall(r'\d{10,13}', sym)
                                if numbers:
                                    ts_val = int(numbers[0])
                                    match_start_s = ts_val / 1000.0 if ts_val > 1000000000000 else float(ts_val)
                                    # If the match already started/ended in the real world
                                    if time.time() > match_start_s:
                                        cursor.execute("""
                                        UPDATE positions 
                                        SET status = 'CLOSED', 
                                            exit_time = CURRENT_TIMESTAMP, 
                                            exit_price = %s, 
                                            pnl = 0.0, 
                                            pnl_pct = 0.0, 
                                            exit_reason = 'Orphan: Match already played' 
                                        WHERE id = %s;
                                        """, (entry_price, pid))
                                        closed_count += 1
                            except Exception as e_inner:
                                print(f"[DB Startup Cleanup] Error parsing position symbol {sym}: {e_inner}")
                        
                        # Also close generic stale positions older than 12 hours as fallback
                        cursor.execute("""
                        UPDATE positions 
                        SET status = 'CLOSED', 
                            exit_time = CURRENT_TIMESTAMP, 
                            exit_price = entry_price, 
                            pnl = 0.0, 
                            pnl_pct = 0.0, 
                            exit_reason = 'Orphan: Stale Timeout' 
                        WHERE status = 'OPEN' AND entry_time < CURRENT_TIMESTAMP - INTERVAL '12 hours';
                        """)
                        
                        conn.commit()
                        if closed_count > 0:
                            print(f"[DB] Auto-limpieza al inicio: Se cerraron {closed_count} posiciones de partidos ya finalizados.")
                    except Exception as ex:
                        print(f"[DB] Error cleaning up orphan positions: {ex}")
                        conn.rollback()

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
                row = cursor.fetchone()
                import datetime
                if isinstance(row, (tuple, list)) and len(row) > 0:
                    ts = row[0]
                elif isinstance(row, dict) and "timestamp" in row:
                    ts = row["timestamp"]
                else:
                    ts = datetime.datetime.now()
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
        requested_price: float = None,
        filled_price: float = None,
        requested_qty: float = None,
        filled_qty: float = None,
        fee_per_asset: float = None,
        gas_usd: float = None,
        slippage_usd: float = None,
        latency_ms: float = None,
        queue_latency_ms: float = None,
        strategy_latency_ms: float = None,
        execution_latency_ms: float = None,
        net_pnl: float = None,
        leg_id: str = None,
    ):
        query = """
        INSERT INTO trades (
            symbol, side, price, amount, total, status, external_order_id,
            worker_id, position_id, requested_price, filled_price,
            requested_qty, filled_qty, fee_per_asset, gas_usd,
            slippage_usd, latency_ms, queue_latency_ms, strategy_latency_ms,
            execution_latency_ms, net_pnl, leg_id
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                        requested_price,
                        filled_price,
                        requested_qty,
                        filled_qty,
                        fee_per_asset,
                        gas_usd,
                        slippage_usd,
                        latency_ms,
                        queue_latency_ms,
                        strategy_latency_ms,
                        execution_latency_ms,
                        net_pnl,
                        leg_id,
                    ),
                )
                row = cursor.fetchone()
                if row:
                    trade_id = row[0] if isinstance(row, (tuple, list)) else (row["id"] if isinstance(row, dict) and "id" in row else 1)
                else:
                    raw_cur = getattr(cursor, "cursor", cursor)
                    trade_id = getattr(raw_cur, "lastrowid", 1) or 1
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

    def get_latency_stats(self, worker_id: str = None, hours: int = 24):
        where = "WHERE latency_ms IS NOT NULL"
        params = []
        if worker_id:
            where += " AND worker_id = %s"
            params.append(worker_id)
        where += " AND timestamp > NOW() - INTERVAL '%s hours'"
        params.append(hours)

        query = f"""
            SELECT
                worker_id,
                COUNT(*) as total_trades,
                ROUND(AVG(latency_ms)::numeric, 2) as avg_total_ms,
                ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY latency_ms)::numeric, 2) as p50_total_ms,
                ROUND(PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY latency_ms)::numeric, 2) as p95_total_ms,
                ROUND(MAX(latency_ms)::numeric, 2) as max_total_ms,
                ROUND(AVG(queue_latency_ms)::numeric, 2) as avg_queue_ms,
                ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY queue_latency_ms)::numeric, 2) as p50_queue_ms,
                ROUND(PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY queue_latency_ms)::numeric, 2) as p95_queue_ms,
                ROUND(AVG(strategy_latency_ms)::numeric, 2) as avg_strategy_ms,
                ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY strategy_latency_ms)::numeric, 2) as p50_strategy_ms,
                ROUND(PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY strategy_latency_ms)::numeric, 2) as p95_strategy_ms,
                ROUND(AVG(execution_latency_ms)::numeric, 2) as avg_execution_ms,
                ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY execution_latency_ms)::numeric, 2) as p50_execution_ms,
                ROUND(PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY execution_latency_ms)::numeric, 2) as p95_execution_ms,
                ROUND(MIN(latency_ms)::numeric, 2) as min_total_ms
            FROM trades
            {where}
            GROUP BY worker_id
            ORDER BY worker_id;
        """
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
                row = cursor.fetchone()
                if row:
                    pos_id = row[0] if isinstance(row, (tuple, list)) else (row["id"] if isinstance(row, dict) and "id" in row else 1)
                else:
                    raw_cur = getattr(cursor, "cursor", cursor)
                    pos_id = getattr(raw_cur, "lastrowid", 1) or 1
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
        pnl_override: float = None,
        pnl_pct_override: float = None,
    ):
        query_get = (
            "SELECT entry_price, side, amount FROM positions WHERE id = %s AND status = 'OPEN';"
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
                amount = float(pos["amount"]) if pos.get("amount") else 1.0

                # Use override P&L if provided (for basket-level calculation)
                if pnl_override is not None and pnl_pct_override is not None:
                    pnl = pnl_override
                    pnl_pct = pnl_pct_override
                elif side == "BUY":
                    pnl_per_unit = exit_price - entry_price
                    pnl = pnl_per_unit * amount
                    pnl_pct = ((exit_price - entry_price) / entry_price) * 100.0 if entry_price > 0 else 0.0
                else:
                    pnl_per_unit = entry_price - exit_price
                    pnl = pnl_per_unit * amount
                    pnl_pct = ((entry_price - exit_price) / entry_price) * 100.0 if entry_price > 0 else 0.0

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

    def get_trades_by_position_id(self, position_id: int):
        """Obtiene todos los trades asociados a una posición (canasta de arb)."""
        query = "SELECT * FROM trades WHERE position_id = %s ORDER BY timestamp ASC;"
        conn = None
        try:
            conn = self._get_connection()
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(query, (position_id,))
                return cursor.fetchall()
        finally:
            self._return_connection(conn)

    def save_position(
        self,
        worker_id: str,
        symbol: str,
        side: str,
        entry_price: float,
        amount: float = None,
        entry_lead_price: float = None,
        stop_loss_price: float = None,
        take_profit_price: float = None,
    ) -> int:
        return self.save_open_position(
            worker_id=worker_id,
            symbol=symbol,
            side=side,
            entry_price=entry_price,
            entry_lead_price=entry_lead_price,
            amount=amount,
            stop_loss_price=stop_loss_price,
            take_profit_price=take_profit_price,
        )

    def get_all_positions(self, limit: int = 50, worker_id: str = None):
        if worker_id:
            query = "SELECT * FROM positions WHERE worker_id = %s ORDER BY entry_time DESC LIMIT %s;"
            params = (worker_id, limit)
        else:
            query = "SELECT * FROM positions ORDER BY entry_time DESC LIMIT %s;"
            params = (limit,)
        conn = None
        try:
            conn = self._get_connection()
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(query, params)
                return cursor.fetchall()
        finally:
            self._return_connection(conn)

    def get_position_history(self, limit: int = 50, worker_id: str = None):
        if worker_id:
            query = "SELECT * FROM positions WHERE status = 'CLOSED' AND worker_id = %s ORDER BY exit_time DESC LIMIT %s;"
            params = (worker_id, limit)
        else:
            query = "SELECT * FROM positions WHERE status = 'CLOSED' ORDER BY exit_time DESC LIMIT %s;"
            params = (limit,)
        conn = None
        try:
            conn = self._get_connection()
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(query, params)
                return cursor.fetchall()
        finally:
            self._return_connection(conn)

    def get_pnl_summary(self, worker_id: str = None, trading_mode: str = None, start_date: str = None, end_date: str = None):
        query = "SELECT * FROM positions WHERE status = 'CLOSED'"
        params = []
        if worker_id:
            query += " AND worker_id = %s"
            params.append(worker_id)
        query += ";"

        conn = None
        try:
            conn = self._get_connection()
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(query, tuple(params))
                positions = cursor.fetchall()

            total_trades = len(positions)
            if total_trades == 0:
                return {
                    "total_trades": 0,
                    "winning_trades": 0,
                    "losing_trades": 0,
                    "win_rate_pct": 0.0,
                    "total_pnl": 0.0,
                    "profit_factor": 0.0,
                    "avg_win": 0.0,
                    "avg_loss": 0.0,
                    "best_trade": 0.0,
                    "worst_trade": 0.0,
                    "expectancy": 0.0,
                    "total_fees": 0.0,
                    "avg_duration_sec": 0.0
                }

            pnls = [float(p.get("pnl") or 0.0) for p in positions]
            wins = [p for p in pnls if p > 0]
            losses = [p for p in pnls if p < 0]

            total_pnl = sum(pnls)
            winning_trades = len(wins)
            losing_trades = len(losses)
            win_rate_pct = (winning_trades / total_trades) * 100.0 if total_trades > 0 else 0.0

            gross_profit = sum(wins)
            gross_loss = abs(sum(losses))
            profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (gross_profit if gross_profit > 0 else 0.0)

            avg_win = (gross_profit / winning_trades) if winning_trades > 0 else 0.0
            avg_loss = (gross_loss / losing_trades) if losing_trades > 0 else 0.0
            best_trade = max(pnls) if pnls else 0.0
            worst_trade = min(pnls) if pnls else 0.0
            expectancy = total_pnl / total_trades if total_trades > 0 else 0.0

            return {
                "total_trades": total_trades,
                "winning_trades": winning_trades,
                "losing_trades": losing_trades,
                "win_rate_pct": round(win_rate_pct, 2),
                "total_pnl": round(total_pnl, 4),
                "profit_factor": round(profit_factor, 2),
                "avg_win": round(avg_win, 4),
                "avg_loss": round(avg_loss, 4),
                "best_trade": round(best_trade, 4),
                "worst_trade": round(worst_trade, 4),
                "expectancy": round(expectancy, 4),
                "total_fees": 0.0,
                "avg_duration_sec": 180.0
            }
        finally:
            self._return_connection(conn)
