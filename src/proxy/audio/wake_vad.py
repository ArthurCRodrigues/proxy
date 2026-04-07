from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Callable
from pathlib import Path
from time import monotonic
from typing import Any

from proxy.audio.io import AudioIO
from proxy.observability.logger import get_logger
from proxy.orchestrator.event_bus import EventBus
from proxy.stt.deepgram_adapter import DeepgramSTTAdapter
from proxy.types import Event, EventType


def _import_vosk() -> Any:
    try:
        import vosk  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("vosk is required for wake-word detection.") from exc
    return vosk


def contains_wake_phrase(result_json: str, wake_phrases: list[str]) -> bool:
    phrases = [p.lower().strip() for p in wake_phrases if p.strip()]
    if not phrases:
        return False
    text, partial = extract_recognizer_text(result_json)
    if not text and not partial:
        return False
    for wake in phrases:
        pattern = re.compile(rf"\b{re.escape(wake)}\b")
        if pattern.search(text) or pattern.search(partial):
            return True
    return False


def extract_recognizer_text(result_json: str) -> tuple[str, str]:
    try:
        payload = json.loads(result_json)
    except json.JSONDecodeError:
        return "", ""
    text = str(payload.get("text", "")).lower().strip()
    partial = str(payload.get("partial", "")).lower().strip()
    return text, partial


class WakeVadEngine:
    def __init__(
        self,
        event_bus: EventBus,
        audio_io: AudioIO,
        sample_rate: int,
        wake_phrase: str,
        wake_aliases: str,
        vosk_model_path: str,
        debug_transcripts: bool = False,
        wake_enabled: Callable[[], bool] | None = None,
        wake_retrigger_cooldown_ms: int = 1500,
        wake_rearm_guard_ms: int = 1200,
        wake_match_partial: bool = False,
        stt_adapter: DeepgramSTTAdapter | None = None,
        stt_gate_allow: Callable[[], bool] | None = None,
        stopword_phrases: list[str] | None = None,
        stopword_enabled: Callable[[], bool] | None = None,
        stopword_cooldown_ms: int = 1500,
    ) -> None:
        self._event_bus = event_bus
        self._audio_io = audio_io
        self._sample_rate = sample_rate
        parsed_aliases = [p.strip() for p in wake_aliases.split(",") if p.strip()]
        primary = wake_phrase.strip()
        if primary and primary not in parsed_aliases:
            parsed_aliases.insert(0, primary)
        self._wake_phrases = parsed_aliases
        self._vosk_model_path = Path(vosk_model_path)
        self._logger = get_logger("proxy.wake_vad")
        self._task: asyncio.Task[None] | None = None
        self._running = False
        self._debug_transcripts = debug_transcripts
        self._wake_enabled = wake_enabled
        self._wake_retrigger_cooldown_s = wake_retrigger_cooldown_ms / 1000.0
        self._wake_rearm_guard_s = wake_rearm_guard_ms / 1000.0
        self._wake_match_partial = wake_match_partial
        self._last_wake_at = 0.0
        self._wake_armed = True
        self._idle_entered_at = monotonic() - self._wake_rearm_guard_s
        self._wake_enabled_last: bool | None = None
        self._stt = stt_adapter
        self._stt_gate_allow = stt_gate_allow
        self._recognizer: Any | None = None
        self._stopword_phrases = stopword_phrases or []
        self._stopword_enabled = stopword_enabled
        self._stopword_cooldown_s = stopword_cooldown_ms / 1000.0
        self._last_stopword_at = 0.0

    async def start(self) -> None:
        if self._running:
            return
        if not self._vosk_model_path.exists():
            raise RuntimeError(
                f"Vosk model not found at {self._vosk_model_path}. "
                "Download and extract a Vosk model to this path."
            )
        vosk = _import_vosk()
        model = vosk.Model(str(self._vosk_model_path))
        self._audio_io.start(asyncio.get_running_loop())
        effective_sr = self._audio_io.actual_sample_rate
        self._recognizer = vosk.KaldiRecognizer(model, effective_sr)
        if effective_sr != self._sample_rate:
            self._logger.warning(
                "Adjusted input sample rate from %s to %s for device compatibility",
                self._sample_rate,
                effective_sr,
            )
        self._running = True
        if self._stt is not None:
            await self._stt.start_stream(sample_rate=effective_sr)
        self._logger.info(
            "Wake engine active with aliases=%s sample_rate=%s",
            ",".join(self._wake_phrases),
            effective_sr,
        )
        self._task = asyncio.create_task(self._run())
        self._task.add_done_callback(self._on_task_done)

    async def stop(self) -> None:
        self._running = False
        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        if self._stt is not None:
            await self._stt.cancel()
        self._audio_io.stop()

    async def _run(self) -> None:
        assert self._recognizer is not None

        while self._running:
            try:
                chunk = await self._audio_io.read_chunk(timeout_s=1.0)
            except TimeoutError:
                continue
            can_send_stt = self._stt_gate_allow() if self._stt_gate_allow is not None else True
            if self._stt is not None and self._stt.ready() and can_send_stt:
                await self._stt.push_audio(chunk)

            if self._recognizer.AcceptWaveform(chunk):
                result = self._recognizer.Result()
                if self._debug_transcripts:
                    text, _ = extract_recognizer_text(result)
                    if text:
                        self._logger.debug("Wake result text: %s", text)
                # Stopword check (active during THINKING/SPEAKING)
                if self._stopword_should_trigger() and contains_wake_phrase(result, self._stopword_phrases):
                    await self._event_bus.publish(Event(type=EventType.INTERRUPT))
                    self._last_stopword_at = monotonic()
                    self._reset_wake_recognizer()
                    self._logger.info("Stopword detected — interrupting")
                # Wake check (active during IDLE)
                elif self._wake_should_trigger() and contains_wake_phrase(result, self._wake_phrases):
                    await self._event_bus.publish(Event(type=EventType.WAKE))
                    self._wake_armed = False
                    self._last_wake_at = monotonic()
                    self._reset_wake_recognizer()
                    self._logger.info("Wake phrase detected")
            else:
                partial = self._recognizer.PartialResult()
                if self._debug_transcripts:
                    _, partial_text = extract_recognizer_text(partial)
                    if partial_text:
                        self._logger.debug("Wake partial text: %s", partial_text)
                if self._wake_match_partial and contains_wake_phrase(partial, self._wake_phrases):
                    await self._event_bus.publish(Event(type=EventType.WAKE))
                    self._wake_armed = False
                    self._last_wake_at = monotonic()
                    self._reset_wake_recognizer()
                    self._logger.info("Wake phrase detected (partial)")

    def _on_task_done(self, task: asyncio.Task[None]) -> None:
        try:
            exc = task.exception()
        except asyncio.CancelledError:
            return
        if exc is not None:
            self._logger.error("Wake engine loop crashed: %s", exc)

    def _wake_should_trigger(self) -> bool:
        if self._wake_enabled is not None:
            wake_enabled = self._wake_enabled()
            if wake_enabled != self._wake_enabled_last:
                self._reset_wake_recognizer()
                now = monotonic()
                if wake_enabled:
                    if self._wake_enabled_last is None:
                        self._idle_entered_at = now - self._wake_rearm_guard_s
                    else:
                        self._idle_entered_at = now
                else:
                    self._wake_armed = True
                    self._idle_entered_at = now
                self._wake_enabled_last = wake_enabled

            if not wake_enabled:
                return False
            if not self._wake_armed:
                return False
            if monotonic() - self._idle_entered_at < self._wake_rearm_guard_s:
                return False
        if monotonic() - self._last_wake_at < self._wake_retrigger_cooldown_s:
            return False
        return True

    def _stopword_should_trigger(self) -> bool:
        if not self._stopword_phrases:
            return False
        if self._stopword_enabled is not None and not self._stopword_enabled():
            return False
        if monotonic() - self._last_stopword_at < self._stopword_cooldown_s:
            return False
        return True

    def _reset_wake_recognizer(self) -> None:
        if self._recognizer is None:
            return
        reset = getattr(self._recognizer, "Reset", None)
        if callable(reset):
            try:
                reset()
            except Exception:
                self._logger.debug("Wake recognizer reset failed", exc_info=True)
