from __future__ import annotations

from collections import Counter
from threading import Lock


class InMemoryMetrics:
    def __init__(self) -> None:
        self._counter: Counter[str] = Counter()
        self._lock = Lock()

    def inc(self, key: str, value: int = 1) -> None:
        with self._lock:
            self._counter[key] += value

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return dict(self._counter)
