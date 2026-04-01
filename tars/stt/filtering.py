from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from time import monotonic


def normalize_text(text: str) -> str:
    return " ".join(text.lower().strip().split())


@dataclass
class EchoFilter:
    similarity_threshold: float = 0.78
    window_seconds: float = 6.0
    max_history: int = 12
    _history: deque[tuple[float, str]] = field(default_factory=deque)

    def record_assistant_text(self, text: str) -> None:
        normalized = normalize_text(text)
        if not normalized:
            return
        now = monotonic()
        self._history.append((now, normalized))
        while len(self._history) > self.max_history:
            self._history.popleft()
        self._prune(now)

    def is_echo(self, text: str) -> bool:
        candidate = normalize_text(text)
        if not candidate:
            return False
        now = monotonic()
        self._prune(now)
        for _, spoken in self._history:
            if spoken == candidate:
                return True
            ratio = SequenceMatcher(None, candidate, spoken).ratio()
            if ratio >= self.similarity_threshold:
                return True
        return False

    def _prune(self, now: float) -> None:
        while self._history and (now - self._history[0][0]) > self.window_seconds:
            self._history.popleft()


@dataclass
class SpeechGate:
    hold_ms: int = 900
    _blocked_until: float = 0.0

    def block(self) -> None:
        self._blocked_until = monotonic() + (self.hold_ms / 1000.0)

    def allow(self) -> bool:
        return monotonic() >= self._blocked_until
