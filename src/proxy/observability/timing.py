from __future__ import annotations

from time import monotonic

from proxy.observability.logger import get_logger

_logger = get_logger("proxy.timing")


class TurnTimer:
    def __init__(self) -> None:
        self._stamps: dict[str, float] = {}

    def stamp(self, name: str) -> None:
        self._stamps[name] = monotonic()

    def elapsed_ms(self, start: str, end: str) -> int | None:
        s = self._stamps.get(start)
        e = self._stamps.get(end)
        if s is None or e is None:
            return None
        return int((e - s) * 1000)

    def summary(self) -> str:
        parts: list[str] = []
        for start, end, label in [
            ("wake", "ready", "wake"),
            ("ready", "user_final", "listen"),
            ("user_final", "first_partial", "copilot_ttfb"),
            ("user_final", "assistant_final", "copilot_total"),
            ("first_partial", "first_tts", "tts_ttfb"),
            ("wake", "assistant_final", "total"),
        ]:
            ms = self.elapsed_ms(start, end)
            if ms is not None:
                parts.append(f"{label}={ms}ms")
        return " ".join(parts) if parts else "no timing data"

    def log_summary(self) -> None:
        _logger.info("TURN_TIMING %s", self.summary())
