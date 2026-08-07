"""
BoundedDict — dict with max size and automatic LRU eviction.

Prevents memory leaks from unbounded global dicts that accumulate entries forever.
"""

import time
import threading
from collections import OrderedDict
from typing import Any, Optional


class BoundedDict:
    """Dict with max size. Evicts oldest entries when full."""

    def __init__(self, max_size: int = 500):
        self._data = OrderedDict()
        self._max_size = max_size
        self._lock = threading.Lock()

    def __setitem__(self, key: str, value: Any):
        with self._lock:
            if key in self._data:
                self._data.move_to_end(key)
            self._data[key] = value
            while len(self._data) > self._max_size:
                self._data.popitem(last=False)

    def __getitem__(self, key: str) -> Any:
        with self._lock:
            return self._data[key]

    def __contains__(self, key: str) -> bool:
        with self._lock:
            return key in self._data

    def get(self, key: str, default=None) -> Any:
        with self._lock:
            return self._data.get(key, default)

    def pop(self, key: str, *args) -> Any:
        with self._lock:
            return self._data.pop(key, *args)

    def discard(self, key: str):
        with self._lock:
            self._data.pop(key, None)

    def __len__(self) -> int:
        with self._lock:
            return len(self._data)

    def keys(self):
        with self._lock:
            return list(self._data.keys())

    def values(self):
        with self._lock:
            return list(self._data.values())

    def items(self):
        with self._lock:
            return list(self._data.items())

    def clear(self):
        with self._lock:
            self._data.clear()

    def __iter__(self):
        with self._lock:
            return iter(list(self._data.keys()))

    def evict_older_than(self, max_age_seconds: float, ts_key: str = "updated_at"):
        """Evict entries older than max_age_seconds based on a timestamp field."""
        cutoff = time.time() - max_age_seconds
        with self._lock:
            keys_to_remove = [
                k for k, v in self._data.items()
                if isinstance(v, dict) and v.get(ts_key, 0) < cutoff
            ]
            for k in keys_to_remove:
                del self._data[k]


class BoundedTimeDict:
    """Dict where entries auto-expire after TTL seconds."""

    def __init__(self, max_size: int = 500, ttl_seconds: float = 3600):
        self._data = OrderedDict()
        self._max_size = max_size
        self._ttl = ttl_seconds
        self._lock = threading.Lock()

    def __setitem__(self, key: str, value: Any):
        with self._lock:
            self._data[key] = (value, time.time())
            self._data.move_to_end(key)
            self._evict_expired()
            while len(self._data) > self._max_size:
                self._data.popitem(last=False)

    def get(self, key: str, default=None) -> Any:
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                return default
            value, ts = entry
            if time.time() - ts > self._ttl:
                del self._data[key]
                return default
            self._data.move_to_end(key)
            return value

    def __contains__(self, key: str) -> bool:
        return self.get(key) is not None

    def pop(self, key: str, *args) -> Any:
        with self._lock:
            entry = self._data.pop(key, *args)
            if entry is None:
                return entry
            if isinstance(entry, tuple) and len(entry) == 2:
                return entry[0]
            return entry

    def discard(self, key: str):
        with self._lock:
            self._data.pop(key, None)

    def _evict_expired(self):
        now = time.time()
        keys_to_remove = [
            k for k, (_, ts) in self._data.items()
            if now - ts > self._ttl
        ]
        for k in keys_to_remove:
            del self._data[k]

    def cleanup(self):
        """Manual cleanup of expired entries."""
        with self._lock:
            self._evict_expired()

    def __len__(self) -> int:
        with self._lock:
            return len(self._data)

    def clear(self):
        with self._lock:
            self._data.clear()

    def __iter__(self):
        with self._lock:
            return iter(list(self._data.keys()))
