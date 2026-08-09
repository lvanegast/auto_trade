from typing import Any, Optional, Dict, List, Union
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
            """
            CREATE TABLE IF NOT EXISTS edge_snapshots (
                id SERIAL PRIMARY KEY,
                timestamp TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                worker_id VARCHAR(50) NOT NULL DEFAULT 'worker_2',
                platform_a VARCHAR(50) NOT NULL,
                platform_b VARCHAR(50) NOT NULL,
                event_id VARCHAR(500) NOT NULL,
                event_title VARCHAR(500) NOT NULL,
                edge_pct NUMERIC(10, 4) NOT NULL DEFAULT 0,
                gross_edge_pct NUMERIC(10, 4) NOT NULL DEFAULT 0,
                platform_a_yes_ask NUMERIC(10, 4),
                platform_b_no_ask NUMERIC(10, 4),
                platform_a_depth NUMERIC(18, 4),
                platform_b_depth NUMERIC(18, 4),
                liquidity_verified BOOLEAN NOT NULL DEFAULT FALSE,
                viable BOOLEAN NOT NULL DEFAULT FALSE,
                resolution_status VARCHAR(20) DEFAULT 'pending',
                entry_price NUMERIC(10, 4),
                expected_profit NUMERIC(10, 4),
                actual_profit NUMERIC(10, 4) DEFAULT 0,
                resolved_at TIMESTAMP
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
            "            ALTER TABLE positions ADD COLUMN IF NOT EXISTS entry_hedge_price NUMERIC(18, 8);",
            "ALTER TABLE edge_snapshots ADD COLUMN IF NOT EXISTS category VARCHAR(20) NOT NULL DEFAULT 'sports';",
            "ALTER TABLE edge_snapshots ADD COLUMN IF NOT EXISTS direction VARCHAR(40);",
            "ALTER TABLE edge_snapshots ADD COLUMN IF NOT EXISTS outcomes_count INTEGER DEFAULT 0;",
            "ALTER TABLE edge_snapshots ADD COLUMN IF NOT EXISTS market_slug VARCHAR(255);",
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

    def prune_old_logs(self, days: int = 7):
        """Delete logs older than N days to prevent DB bloat."""
        conn = None
        try:
            conn = self._get_connection()
            with conn.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM logs WHERE timestamp < NOW() - INTERVAL '%s days'",
                    (days,)
                )
                deleted = cursor.rowcount
                conn.commit()
                if deleted > 0:
                    print(f"[DB] Pruned {deleted} old log entries (>{days} days)")
        except Exception as e:
            print(f"[DB] Error pruning logs: {e}")
        finally:
            self._return_connection(conn)

    def record_edge_snapshot(self, snapshot: dict):
        """Persist an observation without creating a trade or position."""
        query = """
            INSERT INTO edge_snapshots
            (platform_a, platform_b, event_id, event_title, edge_pct,
             gross_edge_pct, platform_a_yes_ask, platform_b_no_ask,
             platform_a_depth, platform_b_depth, liquidity_verified, viable,
             category, direction, outcomes_count)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        conn = None
        try:
            conn = self._get_connection()
            with conn.cursor() as cursor:
                cursor.execute(query, (
                    snapshot.get("platform_a", "limitless"),
                    snapshot.get("platform_b", "kalshi"),
                    snapshot.get("event_id", ""),
                    snapshot.get("event_title", ""),
                    snapshot.get("net_edge_pct", 0.0),
                    snapshot.get("gross_edge_pct", 0.0),
                    snapshot.get("platform_a_yes_ask", 0.0),
                    snapshot.get("platform_b_no_ask", 0.0),
                    snapshot.get("platform_a_depth", 0.0),
                    snapshot.get("platform_b_depth", 0.0),
                    snapshot.get("liquidity_verified", False),
                    snapshot.get("viable", False),
                    snapshot.get("category", "sports"),
                    snapshot.get("direction", ""),
                    snapshot.get("outcomes_count", 0),
                ))
                conn.commit()
        finally:
            self._return_connection(conn)

    def record_opportunity(self, opportunity: dict) -> int:
        """Record a detected opportunity and return its ID for tracking.

        Dedup por event_id: si el mercado ya existe, se actualiza la fila en vez de
        insertar duplicados (antes se insertaba una fila nueva por cada scan).
        """
        event_id = opportunity.get("event_id", "")
        if event_id:
            existing_id = self._find_opportunity_id(event_id)
            if existing_id is not None:
                self._refresh_opportunity(opportunity, event_id)
                return existing_id

        query = """
            INSERT INTO edge_snapshots 
            (worker_id, platform_a, platform_b, event_id, event_title, edge_pct,
             gross_edge_pct, platform_a_yes_ask, platform_b_no_ask,
             platform_a_depth, platform_b_depth, liquidity_verified, viable,
             resolution_status, entry_price, expected_profit,
             category, direction, outcomes_count, market_slug)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """
        conn = None
        try:
            conn = self._get_connection()
            with conn.cursor() as cursor:
                cursor.execute(query, (
                    opportunity.get("worker_id", "worker_2"),
                    opportunity.get("platform_a", "limitless"),
                    opportunity.get("platform_b", "kalshi"),
                    opportunity.get("event_id", ""),
                    opportunity.get("event_title", ""),
                    opportunity.get("net_edge_pct", 0.0),
                    opportunity.get("gross_edge_pct", 0.0),
                    opportunity.get("platform_a_yes_ask", 0.0),
                    opportunity.get("platform_b_no_ask", 0.0),
                    opportunity.get("platform_a_depth", 0.0),
                    opportunity.get("platform_b_depth", 0.0),
                    opportunity.get("liquidity_verified", False),
                    opportunity.get("viable", False),
                    "pending",  # resolution_status
                    opportunity.get("entry_price", 0.0),
                    opportunity.get("expected_profit", 0.0),
                    opportunity.get("category", "sports"),
                    opportunity.get("direction", ""),
                    opportunity.get("outcomes_count", 0),
                    opportunity.get("market_slug", ""),
                ))
                row = cursor.fetchone()
                conn.commit()
                return row[0] if row else None
        finally:
            self._return_connection(conn)

    def _find_opportunity_id(self, event_id: str) -> int | None:
        """Retorna el id de la fila existente para event_id (cualquier estado)."""
        conn = None
        try:
            conn = self._get_connection()
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT id FROM edge_snapshots WHERE event_id = %s ORDER BY id DESC LIMIT 1",
                    (event_id,),
                )
                row = cursor.fetchone()
                if row is None:
                    return None
                return row.get("id") if isinstance(row, dict) else row[0]
        finally:
            self._return_connection(conn)

    def _refresh_opportunity(self, opportunity: dict, event_id: str):
        """Actualiza los datos de una oportunidad existente sin tocar resolution_status."""
        conn = None
        try:
            conn = self._get_connection()
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE edge_snapshots SET
                        worker_id=%s, platform_a=%s, platform_b=%s, event_title=%s,
                        edge_pct=%s, gross_edge_pct=%s, platform_a_yes_ask=%s,
                        platform_b_no_ask=%s, platform_a_depth=%s,
                        platform_b_depth=%s, liquidity_verified=%s, viable=%s,
                        entry_price=%s, expected_profit=%s,
                        category=%s, direction=%s, outcomes_count=%s,
                        market_slug=%s
                    WHERE event_id=%s
                    """,
                    (
                        opportunity.get("worker_id", "worker_2"),
                        opportunity.get("platform_a", "limitless"),
                        opportunity.get("platform_b", "kalshi"),
                        opportunity.get("event_title", ""),
                        opportunity.get("net_edge_pct", 0.0),
                        opportunity.get("gross_edge_pct", 0.0),
                        opportunity.get("platform_a_yes_ask", 0.0),
                        opportunity.get("platform_b_no_ask", 0.0),
                        opportunity.get("platform_a_depth", 0.0),
                        opportunity.get("platform_b_depth", 0.0),
                        opportunity.get("liquidity_verified", False),
                        opportunity.get("viable", False),
                        opportunity.get("entry_price", 0.0),
                        opportunity.get("expected_profit", 0.0),
                        opportunity.get("category", "sports"),
                        opportunity.get("direction", ""),
                        opportunity.get("outcomes_count", 0),
                        opportunity.get("market_slug", ""),
                        event_id,
                    ),
                )
                if not self.use_sqlite:
                    conn.commit()
        except Exception as e:
            if conn and not self.use_sqlite:
                conn.rollback()
            print(f"[DB ERROR] Error actualizando oportunidad existente: {e}")
        finally:
            self._return_connection(conn)

    def update_opportunity_resolution(self, opportunity_id: Any, resolution: str, actual_profit: float = 0.0):
        """Update an opportunity with its resolution outcome (by integer ID or string event_id).

        En el caso string, además del match exacto se marca TODAS las filas cuyo
        event_id contenga el market_slug (sin prefijo de plataforma), para que
        prefijos distintos (limitless_sniper_ / limitless_sport_ / limitless_crypto_)
        del mismo mercado queden resueltos y salgan de la cola de pending.
        """
        if isinstance(opportunity_id, int):
            query = """
                UPDATE edge_snapshots 
                SET resolution_status = %s, 
                    actual_profit = %s,
                    resolved_at = CURRENT_TIMESTAMP
                WHERE id = %s
            """
            params = (resolution, actual_profit, opportunity_id)
        else:
            raw = str(opportunity_id)
            slug = self._strip_platform_prefix(raw)
            query = """
                UPDATE edge_snapshots 
                SET resolution_status = %s, 
                    actual_profit = %s,
                    resolved_at = CURRENT_TIMESTAMP
                WHERE event_id = %s OR event_id LIKE %s
            """
            params = (resolution, actual_profit, raw, f"%{slug}%")
        conn = None
        try:
            conn = self._get_connection()
            with conn.cursor() as cursor:
                cursor.execute(query, params)
                if not self.use_sqlite:
                    conn.commit()
        except Exception as e:
            if conn and not self.use_sqlite:
                conn.rollback()
            print(f"[DB ERROR] Error actualizando resolucion de oportunidad: {e}")
        finally:
            self._return_connection(conn)

    @staticmethod
    def _strip_platform_prefix(value: str) -> str:
        """Elimina el prefijo de plataforma de un event_id para obtener el slug."""
        for prefix in ("limitless_sniper_", "limitless_sport_", "limitless_crypto_",
                       "polymarket_", "limitless_"):
            if value.startswith(prefix):
                return value[len(prefix):]
        return value

    def mark_stale_pending_opportunities(self, stale_hours: int = 24) -> int:
        """Marca oportunidades pendientes viejas como 'stale' para no generar alertas duplicadas."""
        if self.use_sqlite:
            query = """
                UPDATE edge_snapshots
                SET resolution_status = 'stale', resolved_at = datetime('now')
                WHERE resolution_status = 'pending'
                  AND timestamp < datetime('now', '-' || ? || ' hours')
            """
        else:
            query = """
                UPDATE edge_snapshots
                SET resolution_status = 'stale', resolved_at = CURRENT_TIMESTAMP
                WHERE resolution_status = 'pending'
                  AND timestamp < CURRENT_TIMESTAMP - (%s || ' hours')::interval
            """
        conn = None
        try:
            conn = self._get_connection()
            with conn.cursor() as cursor:
                cursor.execute(query, (stale_hours,))
                if not self.use_sqlite:
                    conn.commit()
                return cursor.rowcount
        except Exception as e:
            if conn and not self.use_sqlite:
                conn.rollback()
            print(f"[DB ERROR] Error marcando oportunidades stale: {e}")
            return 0
        finally:
            self._return_connection(conn)

    def get_pending_opportunities(self):
        """Get all opportunities that haven't been resolved yet."""
        query = """
            SELECT id, event_id, event_title, edge_pct, platform_a_yes_ask, 
                   platform_b_no_ask, entry_price, expected_profit, timestamp,
                   market_slug, category, direction, outcomes_count
            FROM edge_snapshots 
            WHERE resolution_status = 'pending'
            ORDER BY timestamp DESC
        """
        conn = None
        try:
            conn = self._get_connection()
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(query)
                return cursor.fetchall()
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

    def save_edge_snapshot(
        self,
        worker_id: str,
        platform_a: str,
        platform_b: str,
        event_id: str,
        event_title: str,
        edge_pct: float,
        gross_edge_pct: float = 0.0,
        platform_a_yes_ask: float = None,
        platform_b_no_ask: float = None,
        platform_a_depth: float = None,
        platform_b_depth: float = None,
        liquidity_verified: bool = False,
        viable: bool = False,
        direction: str = "",
        outcomes_count: int = 0,
        market_slug: str = "",
        entry_price: float = None,
        expected_profit: float = None,
        category: str = "sports",
    ):
        """Registra una observación de edge delegando en record_opportunity.

        record_opportunity ya tiene el DEDUP por event_id (INSERT si no existe,
        UPDATE vía _refresh_opportunity si ya existe), evitando filas duplicadas
        por cada scan del feeder (polling ~3-5s). Antes este método hacía un
        INSERT puro, inflando el paper PnL con el mismo evento decenas de veces
        (ej. Oviedo vs Le Havre 58 filas, Atlético vs Málaga 108).
        """
        self.record_opportunity({
            "worker_id": worker_id,
            "platform_a": platform_a,
            "platform_b": platform_b,
            "event_id": event_id,
            "event_title": event_title,
            "net_edge_pct": edge_pct,
            "gross_edge_pct": gross_edge_pct,
            "platform_a_yes_ask": platform_a_yes_ask,
            "platform_b_no_ask": platform_b_no_ask,
            "platform_a_depth": platform_a_depth,
            "platform_b_depth": platform_b_depth,
            "liquidity_verified": liquidity_verified,
            "viable": viable,
            "category": category,
            "direction": direction,
            "outcomes_count": outcomes_count,
            "market_slug": market_slug,
            "entry_price": entry_price if entry_price is not None else 0.0,
            "expected_profit": expected_profit if expected_profit is not None else 0.0,
        })

    def get_edge_snapshots(self, worker_id: str = None, limit: int = 100, viable_only: bool = False):
        query = "SELECT * FROM edge_snapshots WHERE 1=1"
        params = []
        if worker_id:
            query += " AND worker_id = %s"
            params.append(worker_id)
        if viable_only:
            query += " AND viable = TRUE"
        query += " ORDER BY id DESC LIMIT %s;"
        params.append(limit)

        conn = None
        try:
            conn = self._get_connection()
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(query, tuple(params))
                return cursor.fetchall()
        except Exception as e:
            print(f"[DB ERROR] Error obteniendo edge_snapshots: {e}")
            return []
        finally:
            self._return_connection(conn)

    def get_observation_performance(self, category: str = None, limit: int = 500):
        """Paper PnL de oportunidades en observación (sin trades reales).

        Calcula el PnL hipotético de cada oportunidad registrada en edge_snapshots
        usando el entry_price y la resolución real del mercado:
          - Arbitraje 1xN garantizado: si se compró TODO el paquete por entry_price,
            al settlement recibe $1.00 (BUY_ALL_YES) o $(N-1) (BUY_ALL_NO), por lo que
            el PnL paper = (payout - entry_price) y es GARANTIZADO si los fills pasan.
          - Estrategias direccionales (sniper/resolution): el PnL depende del outcome
            ganador (resolved_YES / resolved_NO).

        El paper PnL asume fills a precios de book y no descuenta gas/fees (friction se
        evalúa por separado en friction_guard). Sirve para medir el RENDIMIENTO de la
        detección: cuánto se habría ganado/perdido si se hubiera ejecutado.
        """
        query = """
            SELECT id, worker_id, event_id, event_title, category, direction,
                   outcomes_count, edge_pct, entry_price, expected_profit,
                   resolution_status, actual_profit, timestamp, resolved_at
            FROM edge_snapshots
            WHERE 1=1
        """
        params = []
        if category:
            query += " AND category = %s"
            params.append(category)
        query += " ORDER BY id DESC LIMIT %s;"
        params.append(limit)

        rows = []
        conn = None
        try:
            conn = self._get_connection()
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(query, tuple(params))
                rows = cursor.fetchall()
        except Exception as e:
            print(f"[DB ERROR] Error obteniendo observation performance: {e}")
            return {"rows": [], "summary": {}, "by_category": {}}
        finally:
            self._return_connection(conn)

        def _paper_pnl(row):
            resolution = row.get("resolution_status") or "pending"
            entry = float(row.get("entry_price") or 0.0)
            direction = row.get("direction") or ""
            outcome_count = int(row.get("outcomes_count") or 0)
            if entry <= 0:
                return None

            # Estrategias direccionales (resolution sniper compra YES ~0.985-0.995):
            # gana $1 si YES resuelve, pierde todo si NO.
            if direction in ("BUY_YES", "SNIPER_YES", "") and resolution == "resolved_YES":
                return 1.0 - entry
            if direction in ("BUY_YES", "SNIPER_YES", "") and resolution == "resolved_NO":
                return -entry
            # Sniper del lado NO: gana $1 si NO resuelve, pierde todo si YES.
            if direction == "SNIPER_NO" and resolution == "resolved_NO":
                return 1.0 - entry
            if direction == "SNIPER_NO" and resolution == "resolved_YES":
                return -entry

            # Arbitraje 1xN garantizado: comprar todo el paquete a entry_price.
            if direction in ("BUY_ALL_YES", "BUY_ALL_YES_1XN"):
                payout = 1.0
                return payout - entry
            if direction in ("BUY_ALL_NO", "BUY_ALL_NO_1XN"):
                # Comprar NO de N outcomes: pagan (N-1) outcomes -> $(N-1)
                if outcome_count > 0:
                    payout = outcome_count - 1
                    return payout - entry
                return None

            # Fallback genérico: si no se conoce la dirección, solo arbitrajes con
            # entry_price < $1 (dual YES+NO intra-platform paga $1 al settlement).
            if entry < 1.0 and resolution == "resolved_YES":
                return 1.0 - entry
            if entry < 1.0 and resolution == "resolved_NO":
                return -entry
            return None

        enriched = []
        summary = {
            "total_opportunities": 0,
            "resolved": 0,
            "pending": 0,
            "wins": 0,
            "losses": 0,
            "total_paper_pnl": 0.0,
            "avg_edge_pct": 0.0,
            "win_rate_pct": 0.0,
        }
        by_category = {}

        for row in rows:
            resolution = row.get("resolution_status") or "pending"
            entry = float(row.get("entry_price") or 0.0)
            cat = row.get("category") or "sports"
            pnl = _paper_pnl(row)

            item = dict(row)
            item["paper_pnl"] = pnl
            item["paper_pnl_per_contract"] = pnl if pnl is not None else None
            enriched.append(item)

            if cat not in by_category:
                by_category[cat] = {
                    "total_opportunities": 0,
                    "resolved": 0,
                    "pending": 0,
                    "wins": 0,
                    "losses": 0,
                    "total_paper_pnl": 0.0,
                    "avg_edge_pct": 0.0,
                    "win_rate_pct": 0.0,
                }
            c = by_category[cat]
            c["total_opportunities"] += 1
            if resolution == "pending":
                c["pending"] += 1
            else:
                c["resolved"] += 1
                if pnl is not None:
                    if pnl > 0:
                        c["wins"] += 1
                    elif pnl < 0:
                        c["losses"] += 1
                    c["total_paper_pnl"] += pnl
            edge_val = float(row.get("edge_pct") or 0.0)
            c["avg_edge_pct"] += edge_val

            summary["total_opportunities"] += 1
            if resolution == "pending":
                summary["pending"] += 1
            else:
                summary["resolved"] += 1
                if pnl is not None:
                    if pnl > 0:
                        summary["wins"] += 1
                    elif pnl < 0:
                        summary["losses"] += 1
                    summary["total_paper_pnl"] += pnl
            summary["avg_edge_pct"] += edge_val

        for bucket in (summary, *by_category.values()):
            if bucket["total_opportunities"] > 0:
                bucket["avg_edge_pct"] = bucket["avg_edge_pct"] / bucket["total_opportunities"]
            decided = bucket["wins"] + bucket["losses"]
            bucket["win_rate_pct"] = (bucket["wins"] / decided * 100) if decided else 0.0

        return {"rows": enriched, "summary": summary, "by_category": by_category}
