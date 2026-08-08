"""
Limpieza de la DB de observación (edge_snapshots) en Railway.

Uso constante durante pruebas: permite borrar oportunidades de estrategias
pasadas para evaluar solo la configuración actual sin datos contaminados.

Requisitos:
  - CLI de Railway autenticado (`railway whoami`)
  - Clave SSH registrada (`railway ssh keys add`) para el túnel
  - psycopg2 instalado localmente

Ejemplos:
  # Borrar solo el sniper (worker_7 / limitless_sniper_*) — default
  python scripts/clean_observation_db.py

  # Borrar todo edge_snapshots
  python scripts/clean_observation_db.py --scope all

  # Borrar solo deportes (NO sniper)
  python scripts/clean_observation_db.py --scope sports

  # Puerto de túnel local distinto
  python scripts/clean_observation_db.py --port 55433
"""

import argparse
import socket
import subprocess
import sys
import time

import psycopg2

DEFAULT_PORT = 55432
DB_NAME = "railway"
DB_USER = "postgres"


def _wait_port(port: int, timeout: int = 90) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=2):
                return True
        except OSError:
            time.sleep(2)
    return False


def _open_tunnel(port: int) -> subprocess.Popen:
    log = f"{__file__}.tunnel.log"
    proc = subprocess.Popen(
        [
            "railway", "connect", "postgres",
            "--environment", "production",
            "--tunnel-only", "--port", str(port),
        ],
        stdout=open(log, "w"),
        stderr=subprocess.STDOUT,
    )
    if not _wait_port(port):
        proc.terminate()
        print(f"ERROR: el túnel no se abrió en 127.0.0.1:{port}. Revisa {log}")
        sys.exit(1)
    return proc


def _clean(port: int, password: str, scope: str):
    conn = psycopg2.connect(
        host="127.0.0.1", port=port, dbname=DB_NAME, user=DB_USER, password=password
    )
    conn.autocommit = False
    cur = conn.cursor()
    try:
        where = {
            "sniper": "worker_id='worker_7' OR event_id LIKE 'limitless_sniper_%'",
            "sports": "worker_id <> 'worker_7' AND event_id NOT LIKE 'limitless_sniper_%'",
            "all": "TRUE",
        }[scope]

        cur.execute(f"SELECT COUNT(*) FROM edge_snapshots WHERE {where}")
        before = cur.fetchone()[0]
        print(f"Filas a borrar [{scope}]: {before}")

        cur.execute(f"DELETE FROM edge_snapshots WHERE {where}")
        print(f"Borradas: {cur.rowcount}")
        conn.commit()

        cur.execute("SELECT COUNT(*) FROM edge_snapshots")
        print(f"Total edge_snapshots después: {cur.fetchone()[0]}")
        cur.execute(
            "SELECT resolution_status, COUNT(*) FROM edge_snapshots "
            "GROUP BY resolution_status ORDER BY 2 DESC"
        )
        for r in cur.fetchall():
            print("  ", r[0], r[1])
    except Exception as e:
        conn.rollback()
        print(f"ERROR, rollback: {e}")
        sys.exit(1)
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--scope", choices=["sniper", "sports", "all"], default="sniper",
        help="Qué borrar: sniper (default), sports (todo menos sniper), all",
    )
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()

    password = input("Password de Postgres de Railway: ").strip()
    if not password:
        print("Password requerida.")
        sys.exit(1)

    print(f"Abriendo túnel a Postgres en 127.0.0.1:{args.port} ...")
    proc = _open_tunnel(args.port)
    try:
        _clean(args.port, password, args.scope)
    finally:
        proc.terminate()
        proc.wait(timeout=10)
        print("Túnel cerrado.")


if __name__ == "__main__":
    main()
