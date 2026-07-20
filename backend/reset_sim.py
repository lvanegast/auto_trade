import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.database import DatabaseManager


def reset_db():
    db = DatabaseManager()
    conn = db._get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM portfolio_state WHERE worker_id IN ('worker_2', 'worker_3', 'worker_4');"
            )
            cur.execute(
                "DELETE FROM positions WHERE worker_id IN ('worker_2', 'worker_3', 'worker_4');"
            )
            conn.commit()
            print("Base de datos de simulación limpiada exitosamente.")
    finally:
        db._return_connection(conn)


if __name__ == "__main__":
    reset_db()
