"""
LatencyTracker — mide latencia real de llamadas API a orderbooks.

Almacena mediciones por plataforma y calcula estadísticas (p50, p95, p99).
NO ejecuta órdenes — solo mide tiempo de respuesta.

Uso:
    tracker = LatencyTracker()
    async with tracker.measure("limitless", "get_orderbook") as measurement:
        orderbook = await market_fetcher.get_orderbook(slug)
        measurement.result = orderbook
    
    stats = tracker.get_stats("limitless")
    print(f"p50={stats['p50_ms']:.1f}ms, p95={stats['p95_ms']:.1f}ms")
"""

import time
import asyncio
from typing import Optional, Dict, Any
from collections import deque
from dataclasses import dataclass, field
from contextlib import asynccontextmanager
import statistics


@dataclass
class LatencyMeasurement:
    """Una sola medición de latencia."""
    platform: str
    operation: str
    start_time: float
    end_time: float = 0.0
    latency_ms: float = 0.0
    success: bool = True
    error: Optional[str] = None
    result: Any = None
    
    def finish(self):
        self.end_time = time.time()
        self.latency_ms = (self.end_time - self.start_time) * 1000


class LatencyTracker:
    """
    Singleton que almacena mediciones de latencia real por plataforma.
    
    Cada feeder debe llamar measure() al hacer llamadas API para cronometrar
    el tiempo real de ida y vuelta al servidor.
    """
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._measurements: Dict[str, deque] = {}
            cls._instance._max_history = 200  # Últimas 200 mediciones por plataforma
        return cls._instance
    
    @asynccontextmanager
    async def measure(self, platform: str, operation: str):
        """
        Context manager para medir latencia de una operación async.
        
        Uso:
            async with tracker.measure("limitless", "get_orderbook") as m:
                result = await some_api_call()
                m.result = result
        """
        measurement = LatencyMeasurement(
            platform=platform,
            operation=operation,
            start_time=time.time(),
        )
        
        try:
            yield measurement
            measurement.success = True
        except Exception as e:
            measurement.success = False
            measurement.error = str(e)
            raise
        finally:
            measurement.finish()
            self._record(measurement)
    
    def _record(self, measurement: LatencyMeasurement):
        """Almacena una medición (sin el resultado API para ahorrar memoria)."""
        # Strip the full API response to prevent OOM — only store latency stats
        measurement.result = None
        key = f"{measurement.platform}:{measurement.operation}"
        if key not in self._measurements:
            self._measurements[key] = deque(maxlen=self._max_history)
        
        self._measurements[key].append(measurement)
    
    def get_stats(self, platform: str, operation: str = None) -> Dict[str, float]:
        """
        Obtiene estadísticas de latencia para una plataforma.
        
        Returns:
            Dict con p50_ms, p95_ms, p99_ms, avg_ms, min_ms, max_ms, count
        """
        if operation:
            key = f"{platform}:{operation}"
            measurements = self._measurements.get(key, [])
        else:
            # Combinar todas las operaciones de la plataforma
            measurements = []
            for k, v in self._measurements.items():
                if k.startswith(f"{platform}:"):
                    measurements.extend(v)
        
        if not measurements:
            return {
                "p50_ms": 0.0,
                "p95_ms": 0.0,
                "p99_ms": 0.0,
                "avg_ms": 0.0,
                "min_ms": 0.0,
                "max_ms": 0.0,
                "count": 0,
                "success_rate": 0.0,
            }
        
        latencies = [m.latency_ms for m in measurements if m.success]
        success_count = sum(1 for m in measurements if m.success)
        
        if not latencies:
            return {
                "p50_ms": 0.0,
                "p95_ms": 0.0,
                "p99_ms": 0.0,
                "avg_ms": 0.0,
                "min_ms": 0.0,
                "max_ms": 0.0,
                "count": len(measurements),
                "success_rate": 0.0,
            }
        
        sorted_latencies = sorted(latencies)
        count = len(sorted_latencies)
        
        return {
            "p50_ms": sorted_latencies[int(count * 0.5)] if count > 0 else 0.0,
            "p95_ms": sorted_latencies[int(count * 0.95)] if count > 1 else sorted_latencies[-1],
            "p99_ms": sorted_latencies[int(count * 0.99)] if count > 1 else sorted_latencies[-1],
            "avg_ms": statistics.mean(sorted_latencies),
            "min_ms": min(sorted_latencies),
            "max_ms": max(sorted_latencies),
            "count": len(measurements),
            "success_rate": success_count / len(measurements) if measurements else 0.0,
        }
    
    def get_recent_latency_ms(self, platform: str, operation: str = None) -> float:
        """
        Obtiene la latencia más reciente (última medición exitosa).
        Útil para aplicar como delay artificial en simulación.
        """
        if operation:
            key = f"{platform}:{operation}"
            measurements = self._measurements.get(key, [])
        else:
            measurements = []
            for k, v in self._measurements.items():
                if k.startswith(f"{platform}:"):
                    measurements.extend(v)
        
        for m in reversed(measurements):
            if m.success:
                return m.latency_ms
        
        return 0.0
    
    def get_all_stats(self) -> Dict[str, Dict[str, float]]:
        """Obtiene estadísticas de todas las plataformas."""
        stats = {}
        for key in self._measurements:
            platform, operation = key.split(":", 1)
            stats[key] = self.get_stats(platform, operation)
        return stats
    
    def clear(self):
        """Limpia todas las mediciones."""
        self._measurements.clear()


# Singleton global
latency_tracker = LatencyTracker()
