from __future__ import annotations

import asyncio
import base64
import json
from collections.abc import Callable

from proxy.observability.logger import get_logger


class ElevenLabsTTSAdapter:
    def __init__(
        self,
        api_key: str,
        voice_id: str,
        model_id: str = "eleven_multilingual_v2",
        output_format: str = "pcm_22050",
        stability: float = 0.45,
        similarity_boost: float = 0.85,
        style: float = 0.25,
        speed: float = 0.95,
        use_speaker_boost: bool = True,
        on_audio_chunk: Callable[[bytes], None] | None = None,
    ) -> None:
        self._api_key = api_key
        self._voice_id = voice_id
        self._model_id = model_id
        self._output_format = output_format
        self._stability = stability
        self._similarity_boost = similarity_boost
        self._style = style
        self._speed = speed
        self._use_speaker_boost = use_speaker_boost
        self._on_audio_chunk = on_audio_chunk
        self._ws = None
        self._listener_task: asyncio.Task[None] | None = None
        self._logger = get_logger("proxy.tts.elevenlabs")

    def _url(self) -> str:
        return (
            f"wss://api.elevenlabs.io/v1/text-to-speech/{self._voice_id}"
            f"/stream-input?model_id={self._model_id}"
            f"&output_format={self._output_format}"
        )

    async def connect(self) -> None:
        if self._ws is not None:
            return
        if not self._api_key:
            raise RuntimeError("ElevenLabs API key is not configured.")
        if not self._voice_id:
            raise RuntimeError("ElevenLabs voice ID is not configured.")

        import websockets

        self._ws = await websockets.connect(self._url(), ping_interval=10, ping_timeout=20, max_size=10 * 1024 * 1024)
        await self._ws.send(json.dumps({
            "text": " ",
            "voice_settings": {
                "stability": self._stability,
                "similarity_boost": self._similarity_boost,
                "style": self._style,
                "speed": self._speed,
                "use_speaker_boost": self._use_speaker_boost,
            },
            "xi_api_key": self._api_key,
        }))
        self._listener_task = asyncio.create_task(self._listen())
        self._logger.info("ElevenLabs WebSocket connected")

    async def _listen(self) -> None:
        assert self._ws is not None
        try:
            async for raw in self._ws:
                if not isinstance(raw, str):
                    continue
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                audio_b64 = msg.get("audio")
                if audio_b64 and self._on_audio_chunk is not None:
                    self._on_audio_chunk(base64.b64decode(audio_b64))
                if msg.get("isFinal"):
                    break
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._logger.error("ElevenLabs WebSocket listener error: %s", exc)
        finally:
            self._logger.debug("ElevenLabs WebSocket listener closed")

    async def send_text(self, text: str) -> None:
        if not text:
            return
        if self._ws is None:
            await self.connect()
        assert self._ws is not None
        try:
            await self._ws.send(json.dumps({"text": text}))
        except Exception as exc:
            self._logger.error("ElevenLabs send_text error: %s", exc)
            await self._close()
            await self.connect()
            await self._ws.send(json.dumps({"text": text}))

    async def flush(self) -> None:
        if self._ws is None:
            return
        try:
            await self._ws.send(json.dumps({"text": "", "flush": True}))
        except Exception as exc:
            self._logger.error("ElevenLabs flush error: %s", exc)

    async def cancel(self) -> None:
        await self._close()

    async def _close(self) -> None:
        if self._listener_task is not None and not self._listener_task.done():
            self._listener_task.cancel()
            try:
                await self._listener_task
            except asyncio.CancelledError:
                pass
        self._listener_task = None
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass
        self._ws = None
