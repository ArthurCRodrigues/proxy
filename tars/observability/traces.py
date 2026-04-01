from __future__ import annotations

from dataclasses import dataclass
from time import time


@dataclass(frozen=True)
class TracePoint:
    name: str
    ts_ms: int


def now_trace(name: str) -> TracePoint:
    return TracePoint(name=name, ts_ms=int(time() * 1000))
