from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Callable
from urllib.parse import urlencode

from proxy.observability.logger import get_logger


def extract_transcript(raw: str) -> tuple[str, bool, bool] | None:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if payload.get("type") != "Results":
        return None
    alternatives = payload.get("channel", {}).get("alternatives", [])
    if not alternatives:
        return None
    transcript = str(alternatives[0].get("transcript", "")).strip()
    is_final = bool(payload.get("is_final", False))
    speech_final = bool(payload.get("speech_final", False))
    if not transcript and not (is_final or speech_final):
        return None
    return transcript, is_final, speech_final


class DeepgramSTTAdapter:
    def __init__(
        self,
        api_key: str,
        sample_rate: int,
        model: str = "nova-3",
        language: str = "en-US",
        endpointing_enabled: bool = True,
        endpointing_ms: int = 700,
        utterance_end_ms: int = 3500,
        punctuate: bool = True,
        smart_format: bool = True,
        keyterms: tuple[str, ...] = (),
        interim_results: bool = True,
        reconnect_max_attempts: int = 3,
        reconnect_base_delay_ms: int = 200,
    ) -> None:
        self._api_key = api_key
        self._sample_rate = sample_rate
        self._model = model
        self._language = language
        self._endpointing_enabled = endpointing_enabled
        self._endpointing_ms = endpointing_ms
        self._utterance_end_ms = utterance_end_ms
        self._punctuate = punctuate
        self._smart_format = smart_format
        self._keyterms = keyterms
        self._interim_results = interim_results
        self._reconnect_max_attempts = reconnect_max_attempts
        self._reconnect_base_delay_ms = reconnect_base_delay_ms

        self._logger = get_logger("proxy.stt.deepgram")
        self._ws = None
        self._listener_task: asyncio.Task[None] | None = None
        self._on_partial: Callable[[str], None] | None = None
        self._on_final: Callable[[str], None] | None = None
        self._lock = asyncio.Lock()
        self._stopped = False
        self._last_partial_text = ""
        self._assembled_partial_text = ""

    def _url(self) -> str:
        params: list[tuple[str, str]] = [
            ("encoding", "linear16"),
            ("sample_rate", str(self._sample_rate)),
            ("channels", "1"),
            ("model", self._model),
            ("language", self._language),
            ("interim_results", "true" if self._interim_results else "false"),
            (
                "endpointing",
                str(self._endpointing_ms) if self._endpointing_enabled else "false",
            ),
            ("utterance_end_ms", str(self._utterance_end_ms)),
            ("punctuate", "true" if self._punctuate else "false"),
            ("smart_format", "true" if self._smart_format else "false"),
        ]
        params.extend(("keyterm", term) for term in self._keyterms)
        query = urlencode(params)
        return f"wss://api.deepgram.com/v1/listen?{query}"

    async def start_stream(self, sample_rate: int | None = None) -> None:
        async with self._lock:
            if self._ws is not None:
                return
            if not self._api_key:
                raise RuntimeError("Deepgram API key is not configured.")
            if sample_rate is not None:
                self._sample_rate = sample_rate
            self._stopped = False
            self._last_partial_text = ""
            self._assembled_partial_text = ""

            import websockets

            self._ws = await websockets.connect(
                self._url(),
                additional_headers={"Authorization": f"Token {self._api_key}"},
                ping_interval=10,
                ping_timeout=20,
                close_timeout=2,
            )
            self._listener_task = asyncio.create_task(self._listen())
            self._logger.info("Deepgram stream connected")

    async def _listen(self) -> None:
        assert self._ws is not None
        try:
            async for raw in self._ws:
                if not isinstance(raw, str):
                    continue
                self._logger.debug("Deepgram raw: %s", raw[:500])
                self._handle_message(raw)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._logger.error("Deepgram listener error: %s", exc)
            if not self._stopped:
                await self._reconnect()
        finally:
            self._logger.info("Deepgram listener closed")

    def _handle_message(self, raw: str) -> None:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return

        msg_type = payload.get("type", "")

        if msg_type == "UtteranceEnd":
            final_text = (self._last_partial_text or self._assembled_partial_text).strip()
            if final_text:
                self._last_partial_text = ""
                self._assembled_partial_text = ""
                if self._on_final is not None:
                    self._on_final(final_text)
            return

        if msg_type != "Results":
            return

        parsed = extract_transcript(raw)
        if parsed is None:
            return

        transcript, is_final, speech_final = parsed
        if speech_final:
            final_text = self._assemble_final_text(transcript)
            if not final_text:
                return
            self._last_partial_text = ""
            self._assembled_partial_text = ""
            if self._on_final is not None:
                self._on_final(final_text)
        elif is_final:
            if transcript:
                self._last_partial_text = transcript
                self._assembled_partial_text = _merge_partial_utterance(
                    self._assembled_partial_text,
                    transcript,
                )
                if self._on_partial is not None:
                    self._on_partial(transcript)
        else:
            self._last_partial_text = transcript
            self._assembled_partial_text = _merge_partial_utterance(
                self._assembled_partial_text,
                transcript,
            )
            if self._on_partial is not None:
                self._on_partial(transcript)

    async def push_audio(self, data: bytes) -> None:
        if self._ws is None:
            return
        try:
            await self._ws.send(data)
        except Exception as exc:
            self._logger.error("Failed sending audio to Deepgram: %s", exc)

    async def cancel(self) -> None:
        async with self._lock:
            self._stopped = True
            await self._close_connection(await_listener=True)

    def on_partial(self, cb: Callable[[str], None]) -> None:
        self._on_partial = cb

    def on_final(self, cb: Callable[[str], None]) -> None:
        self._on_final = cb

    def ready(self) -> bool:
        return self._ws is not None and _is_ws_open(self._ws)

    async def _reconnect(self) -> None:
        for attempt in range(1, self._reconnect_max_attempts + 1):
            delay = (self._reconnect_base_delay_ms * attempt) / 1000.0
            self._logger.warning("Deepgram reconnect attempt %s in %.2fs", attempt, delay)
            await asyncio.sleep(delay)
            try:
                async with self._lock:
                    await self._close_connection(await_listener=False)
                await self.start_stream(sample_rate=self._sample_rate)
                self._logger.info("Deepgram reconnect succeeded")
                return
            except Exception as exc:
                self._logger.error("Deepgram reconnect attempt %s failed: %s", attempt, exc)
        self._logger.error("Deepgram reconnect exhausted")

    async def _close_connection(self, await_listener: bool) -> None:
        current_task = asyncio.current_task()
        listener_task = self._listener_task
        if listener_task is not None and not listener_task.done():
            if listener_task is not current_task:
                listener_task.cancel()
                if await_listener:
                    try:
                        await listener_task
                    except asyncio.CancelledError:
                        pass
            self._listener_task = None
        else:
            self._listener_task = None

        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass
        self._ws = None
        self._last_partial_text = ""
        self._assembled_partial_text = ""

    def _assemble_final_text(self, final_text: str) -> str:
        candidate = final_text.strip() or self._last_partial_text.strip() or self._assembled_partial_text.strip()
        if not candidate:
            return ""

        assembled = self._assembled_partial_text.strip()
        if not assembled:
            return candidate

        merged = _merge_partial_utterance(assembled, candidate)
        norm_candidate = _normalize_for_compare(candidate)
        norm_merged = _normalize_for_compare(merged)
        if not norm_candidate or not norm_merged:
            return candidate

        extra_words = _word_count(merged) - _word_count(candidate)
        if extra_words >= 2 and (
            norm_merged.endswith(norm_candidate)
            or (norm_candidate in norm_merged and len(norm_merged) >= int(len(norm_candidate) * 1.5))
        ):
            self._logger.debug(
                "Using assembled final from partial history (candidate=%r assembled=%r)",
                candidate,
                merged,
            )
            return merged

        return candidate


def _is_ws_open(ws: object) -> bool:
    closed = getattr(ws, "closed", None)
    if isinstance(closed, bool):
        return not closed

    state = str(getattr(ws, "state", "")).upper()
    if "OPEN" in state:
        return True
    if "CLOSED" in state or "CLOSING" in state:
        return False

    return True


def _normalize_for_compare(text: str) -> str:
    return re.sub(r"[^a-z0-9\s]+", "", text.lower()).strip()


def _word_count(text: str) -> int:
    return len([token for token in text.split() if token])


def _merge_partial_utterance(assembled: str, partial: str) -> str:
    left = assembled.strip()
    right = partial.strip()
    if not right:
        return left
    if not left:
        return right

    norm_left = _normalize_for_compare(left)
    norm_right = _normalize_for_compare(right)
    if not norm_left:
        return right
    if not norm_right:
        return left
    if norm_right in norm_left:
        return left
    if norm_left in norm_right and _word_count(right) >= _word_count(left) - 2:
        return right

    overlap = _token_overlap_count(left, right)
    if overlap > 0:
        left_tokens = left.split()
        right_tokens = right.split()
        return " ".join(left_tokens + right_tokens[overlap:])

    return f"{left} {right}"


def _token_overlap_count(left: str, right: str, max_window: int = 16) -> int:
    left_tokens = left.split()
    right_tokens = right.split()
    max_k = min(len(left_tokens), len(right_tokens), max_window)
    for k in range(max_k, 1, -1):
        l_slice = left_tokens[-k:]
        r_slice = right_tokens[:k]
        l_norm = " ".join(_normalize_for_compare(token) for token in l_slice).strip()
        r_norm = " ".join(_normalize_for_compare(token) for token in r_slice).strip()
        if l_norm and l_norm == r_norm:
            return k
    return 0
