"""
Servidor WebSocket para streaming en tiempo real a clientes del frontend.

Los clientes se conectan a ws://host:8080/ws/{worker_id} y reciben
eventos price_update, trade_update, depth_update, y log en tiempo real.
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger("WebSocketServer")


class WebSocketServer:
    """Singleton que gestiona clientes WebSocket suscritos por worker_id."""

    def __init__(self):
        # {worker_id: set[WebSocket]}
        self._clients: dict[str, set[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket, worker_id: str):
        """Registra un nuevo cliente WebSocket para un worker."""
        await websocket.accept()
        async with self._lock:
            if worker_id not in self._clients:
                self._clients[worker_id] = set()
            self._clients[worker_id].add(websocket)
        logger.info(
            f"[WS] Cliente conectado a worker '{worker_id}' "
            f"(total: {len(self._clients.get(worker_id, set()))})"
        )

    async def disconnect(self, websocket: WebSocket, worker_id: str):
        """Elimina un cliente WebSocket."""
        async with self._lock:
            if worker_id in self._clients:
                self._clients[worker_id].discard(websocket)
                remaining = len(self._clients[worker_id])
                if remaining == 0:
                    del self._clients[worker_id]
                logger.info(
                    f"[WS] Cliente desconectado de worker '{worker_id}' "
                    f"(restantes: {remaining})"
                )

    async def broadcast(self, worker_id: str, event: dict[str, Any]):
        """Envía un evento a todos los clientes suscritos a un worker.

        Si no hay clientes, no hace nada (no bloquea al worker).
        """
        async with self._lock:
            clients = set(self._clients.get(worker_id, set()))

        if not clients:
            return  # Sin clientes, sin overhead

        message = json.dumps(event, default=str)
        dead: list[WebSocket] = []

        for ws in clients:
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)

        # Limpiar clientes muertos
        if dead:
            async with self._lock:
                if worker_id in self._clients:
                    for ws in dead:
                        self._clients[worker_id].discard(ws)

    def has_clients(self, worker_id: str) -> bool:
        """Verifica si hay clientes escuchando (para evitar trabajo innecesario)."""
        clients = self._clients.get(worker_id, set())
        return len(clients) > 0

    @property
    def total_clients(self) -> int:
        return sum(len(s) for s in self._clients.values())


# Singleton global
ws_server = WebSocketServer()


def make_event(event_type: str, data: dict[str, Any]) -> dict[str, Any]:
    """Crea un evento estandarizado con timestamp."""
    return {
        "type": event_type,
        "timestamp": datetime.now().isoformat(),
        "data": data,
    }
