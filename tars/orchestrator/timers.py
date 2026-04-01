from __future__ import annotations

from dataclasses import dataclass
from time import monotonic


@dataclass
class Stopwatch:
    _start: float

    @classmethod
    def start(cls) -> "Stopwatch":
        return cls(_start=monotonic())

    def elapsed_ms(self) -> int:
        return int((monotonic() - self._start) * 1000)
