from __future__ import annotations

import asyncio
import base64
import inspect
import json
from collections.abc import Awaitable, Callable

from proxy.observability.logger import get_logger


class ElevenLabsTTSAdapter:
    def __init__(
        self,
        api_key: str,
        voice_id: str,
        model_id: str = "eleven_multilingual_v2",
        output_format: str = "pcm_22050",
        latency_mode: str = "optimistic",
        stability: float = 0.45,
        similarity_boost: float = 0.85,
        style: float = 0.65,
        speed: float = 0.95,
        use_speaker_boost: bool = True,
        on_audio_chunk: Callable[[bytes], Awaitable[None] | None] | None = None,
    ) -> None:
        self._api_key = api_key
        self._voice_id = voice_id
        self._model_id = model_id
        self._output_format = output_format
        self._latency_mode = latency_mode
        self._stability = stability
        self._similarity_boost = similarity_boost
        self._style = style
        self._speed = speed
        self._use_speaker_boost = use_speaker_boost
        self._on_audio_chunk = on_audio_chunk
        self._ws = None
        self._listener_task: asyncio.Task[None] | None = None
        self._stream_lock = asyncio.Lock()
        self._logger = get_logger("proxy.tts.elevenlabs")

    def _url(self) -> str:
        return (
            f"wss://api.elevenlabs.io/v1/text-to-speech/{self._voice_id}"
            f"/stream-input?model_id={self._model_id}"
            f"&output_format={self._output_format}"
            f"&latency_mode={self._latency_mode}"
        )

    async def start_stream(self) -> None:
        async with self._stream_lock:
            await self._close_stream_locked()
            if not self._api_key:
                raise RuntimeError("ElevenLabs API key is not configured.")
            if not self._voice_id:
                raise RuntimeError("ElevenLabs voice ID is not configured.")

            import websockets

            self._ws = await websockets.connect(self._url(), ping_interval=10, ping_timeout=20)
            ws = self._ws
            await ws.send(
                json.dumps(
                    {
                        "text": " ",
                        "voice_settings": {
                            "stability": self._stability,
                            "similarity_boost": self._similarity_boost,
                            "style": self._style,
                            "speed": self._speed,
                            "use_speaker_boost": self._use_speaker_boost,
                        },
                        "xi_api_key": self._api_key,
                    }
                )
            )
            self._listener_task = asyncio.create_task(self._listen(ws))
            self._logger.info("ElevenLabs WebSocket connected")

    async def _listen(self, ws) -> None:
        try:
            async for raw in ws:
                if not isinstance(raw, str):
                    continue
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                audio_b64 = msg.get("audio")
                if audio_b64 and self._on_audio_chunk is not None:
                    await self._emit_audio_chunk(base64.b64decode(audio_b64))
                if msg.get("isFinal"):
                    break
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._logger.error("ElevenLabs WebSocket listener error: %s", exc)
        finally:
            try:
                await ws.close()
            except Exception:
                pass
            if self._ws is ws:
                self._ws = None
            if self._listener_task is asyncio.current_task():
                self._listener_task = None
            self._logger.debug("ElevenLabs WebSocket listener closed")

    async def push_text(self, text: str) -> None:
        if not text:
            return
        if self._ws is None or self._listener_task is None or self._listener_task.done():
            await self.start_stream()
        assert self._ws is not None
        try:
            await self._ws.send(json.dumps({"text": text}))
        except Exception as exc:
            await self.cancel_stream()
            raise RuntimeError(f"ElevenLabs push_text error: {exc}") from exc

    async def finalize_stream(self) -> None:
        if self._ws is None:
            return
        try:
            await self._ws.send(json.dumps({"text": "", "flush": True}))
        except Exception as exc:
            await self.cancel_stream()
            raise RuntimeError(f"ElevenLabs finalize_stream error: {exc}") from exc
        listener_task = self._listener_task
        if listener_task is None:
            await self.cancel_stream()
            return
        try:
            await asyncio.wait_for(asyncio.shield(listener_task), timeout=5.0)
        except TimeoutError:
            self._logger.warning("Timed out waiting for ElevenLabs stream finalization; closing stream")
            await self.cancel_stream()

    async def cancel_stream(self) -> None:
        async with self._stream_lock:
            await self._close_stream_locked()

    async def close_stream(self) -> None:
        await self.cancel_stream()

    async def _close_stream_locked(self) -> None:
        listener_task = self._listener_task
        current_task = asyncio.current_task()
        if listener_task is not None and listener_task is not current_task and not listener_task.done():
            listener_task.cancel()
            try:
                await listener_task
            except asyncio.CancelledError:
                pass
        self._listener_task = None
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass
        self._ws = None

    async def _emit_audio_chunk(self, chunk: bytes) -> None:
        if self._on_audio_chunk is None:
            return
        callback_result = self._on_audio_chunk(chunk)
        if inspect.isawaitable(callback_result):
            await callback_result

    async def connect(self) -> None:
        await self.start_stream()

    async def send_text(self, text: str) -> None:
        await self.push_text(text)

    async def flush(self) -> None:
        await self.finalize_stream()

    async def cancel(self) -> None:
        await self.cancel_stream()
