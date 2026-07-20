"""
Gestor de conexiones WebSocket reutilizable con resiliencia.

Proporciona:
- AsyncWebSocketManager: para conexiones WebSocket raw (Binance, Kalshi)
- exponential_backoff: generador de delays para reconexión
- Circuit breaker: pausa tras fallos consecutivos
"""

import asyncio
import logging
import time
from abc import ABC, abstractmethod

logger = logging.getLogger("ConnectionManager")


def exponential_backoff(
    base: float = 1.0,
    cap: float = 60.0,
    multiplier: float = 2.0,
    max_failures: int = 5,
    circuit_breaker_pause: float = 30.0,
):
    """Generador de delays para reconexión con circuit breaker.

    Yields:
        (delay_seconds, is_circuit_breaker_active)
    """
    consecutive_failures = 0
    delay = base

    while True:
        if consecutive_failures >= max_failures:
            logger.warning(
                f"Circuit breaker activado tras {consecutive_failures} fallos. "
                f"Pausando {circuit_breaker_pause}s..."
            )
            yield circuit_breaker_pause, True
            # Reset después del circuit breaker
            delay = base
            consecutive_failures = 0
        else:
            yield delay, False
            consecutive_failures += 1
            delay = min(delay * multiplier, cap)

    # Para resetear tras una conexión exitosa, el caller debe recrear el generador


class AsyncWebSocketManager(ABC):
    """Gestor de WebSocket con reconexión automática, health check y circuit breaker.

    Uso:
        class MiFeeder(AsyncWebSocketManager):
            async def on_message(self, data: dict):
                # Procesar mensaje recibido
                ...

        feeder = MiFeeder("wss://...", ping_interval=20)
        await feeder.connect()
    """

    def __init__(
        self,
        url: str,
        ping_interval: float = 20,
        ping_timeout: float = 10,
        health_check_timeout: float = 30.0,
        reconnect_base_delay: float = 1.0,
        reconnect_cap: float = 60.0,
        max_consecutive_failures: int = 5,
        circuit_breaker_pause: float = 30.0,
        name: str = "WebSocket",
    ):
        self.url = url
        self.ping_interval = ping_interval
        self.ping_timeout = ping_timeout
        self.health_check_timeout = health_check_timeout
        self.reconnect_base_delay = reconnect_base_delay
        self.reconnect_cap = reconnect_cap
        self.max_consecutive_failures = max_consecutive_failures
        self.circuit_breaker_pause = circuit_breaker_pause
        self.name = name

        self._running = False
        self._websocket = None
        self._last_message_time: float = 0.0
        self._task: asyncio.Task | None = None
        self._lock = asyncio.Lock()

    @abstractmethod
    async def on_message(self, data: dict):
        """Procesa un mensaje recibido del WebSocket.

        Args:
            data: El mensaje parseado como diccionario (ya decodificado de JSON).
        """
        ...

    async def on_connected(self):
        """Hook llamado tras una conexión exitosa. Sobrescribir si es necesario."""
        logger.info(f"[{self.name}] Conexión establecida a {self.url}")

    async def on_disconnected(self, reason: str = ""):
        """Hook llamado al desconectarse. Sobrescribir si es necesario."""
        logger.warning(f"[{self.name}] Desconectado. {reason}")

    async def connect(self):
        """Inicia la conexión WebSocket con reconexión automática.

        Usa un asyncio.Lock para evitar arranques duplicados.
        """
        async with self._lock:
            if self._running:
                logger.debug(f"[{self.name}] Ya está corriendo, ignorando connect().")
                return

            self._running = True
            self._task = asyncio.create_task(self._run_loop())
            logger.info(f"[{self.name}] Tarea de conexión iniciada.")

    async def disconnect(self):
        """Detiene la conexión y la tarea de reconexión."""
        async with self._lock:
            self._running = False

        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

        await self._close_websocket()
        logger.info(f"[{self.name}] Desconectado y tarea detenida.")

    async def _close_websocket(self):
        if self._websocket:
            try:
                await self._websocket.close()
            except Exception:
                pass
            self._websocket = None

    async def _run_loop(self):
        """Loop principal: conecta, recibe mensajes, reconecta en fallo."""
        import websockets

        backoff = exponential_backoff(
            base=self.reconnect_base_delay,
            cap=self.reconnect_cap,
            max_failures=self.max_consecutive_failures,
            circuit_breaker_pause=self.circuit_breaker_pause,
        )

        while self._running:
            try:
                async with websockets.connect(
                    self.url,
                    ping_interval=self.ping_interval,
                    ping_timeout=self.ping_timeout,
                ) as ws:
                    self._websocket = ws
                    self._last_message_time = time.monotonic()
                    # Reconexión exitosa → resetear backoff
                    backoff = exponential_backoff(
                        base=self.reconnect_base_delay,
                        cap=self.reconnect_cap,
                        max_failures=self.max_consecutive_failures,
                        circuit_breaker_pause=self.circuit_breaker_pause,
                    )
                    await self.on_connected()

                    # Iniciar health check concurrente
                    health_task = asyncio.create_task(self._health_check())

                    try:
                        async for message in ws:
                            if not self._running:
                                break
                            self._last_message_time = time.monotonic()
                            try:
                                data = __import__("json").loads(message)
                                await self.on_message(data)
                            except Exception as e:
                                logger.error(
                                    f"[{self.name}] Error procesando mensaje: {e}"
                                )
                    finally:
                        health_task.cancel()
                        try:
                            await health_task
                        except asyncio.CancelledError:
                            pass

                    await self.on_disconnected("Ciclo de mensajes terminó.")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[{self.name}] Error de conexión: {e}")

            if not self._running:
                break

            # Obtener delay de reconexión
            delay, is_cb = next(backoff)
            status = "CIRCUIT BREAKER" if is_cb else "reconexión"
            logger.info(f"[{self.name}] Esperando {delay:.1f}s para {status}...")
            await asyncio.sleep(delay)

        await self._close_websocket()

    async def _health_check(self):
        """Verifica que se reciban mensajes dentro del timeout configurado."""
        while self._running and self._websocket:
            await asyncio.sleep(5)  # Verificar cada 5 segundos
            elapsed = time.monotonic() - self._last_message_time
            if elapsed > self.health_check_timeout:
                logger.warning(
                    f"[{self.name}] Health check fallido: {elapsed:.1f}s sin mensajes. "
                    f"Forzando reconexión..."
                )
                # Cerrar el WebSocket actual para forzar reconexión
                await self._close_websocket()
                break  # Salir del health check, _run_loop reintentará
