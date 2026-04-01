from __future__ import annotations

import asyncio
from io import BytesIO
import wave

from elevenlabs.core.api_error import ApiError
from tars.audio.assets import PcmAudio
from tars.observability.logger import get_logger

from tars.tts.base import TTSAdapter


class ElevenLabsTTSAdapter(TTSAdapter):
    def __init__(
        self,
        api_key: str,
        voice_id: str,
        model_id: str = "eleven_multilingual_v2",
        output_format: str = "pcm_22050",
        fallback_output_formats: tuple[str, ...] = ("wav_22050",),
        stability: float = 0.45,
        similarity_boost: float = 0.85,
        style: float = 0.25,
        speed: float = 0.95,
        use_speaker_boost: bool = True,
    ) -> None:
        self._api_key = api_key
        self._voice_id = voice_id
        self._model_id = model_id
        self._output_format = output_format
        self._fallback_output_formats = tuple(
            fmt for fmt in fallback_output_formats if fmt and fmt != output_format
        )
        self._stability = stability
        self._similarity_boost = similarity_boost
        self._style = style
        self._speed = speed
        self._use_speaker_boost = use_speaker_boost
        self._cancelled = False
        self._lock = asyncio.Lock()
        self._logger = get_logger("tars.tts.elevenlabs")

    async def synthesize_text(self, text: str) -> PcmAudio:
        async with self._lock:
            self._cancelled = False
            cleaned = text.strip()
            if not cleaned:
                return PcmAudio(data=b"", sample_rate=16000, channels=1, sample_width=2)
            if not self._api_key:
                raise RuntimeError("ElevenLabs API key is not configured.")
            if not self._voice_id:
                raise RuntimeError("ElevenLabs voice ID is not configured.")

            import elevenlabs

            client = elevenlabs.ElevenLabs(api_key=self._api_key)
            formats_to_try = (self._output_format, *self._fallback_output_formats)
            last_error: Exception | None = None
            audio = None
            used_format = self._output_format
            for output_format in formats_to_try:
                try:
                    audio = await asyncio.to_thread(
                        client.text_to_speech.convert,
                        voice_id=self._voice_id,
                        text=cleaned,
                        model_id=self._model_id,
                        output_format=output_format,
                        voice_settings=elevenlabs.VoiceSettings(
                            stability=self._stability,
                            similarity_boost=self._similarity_boost,
                            style=self._style,
                            speed=self._speed,
                            use_speaker_boost=self._use_speaker_boost,
                        ),
                    )
                    used_format = output_format
                    break
                except ApiError as exc:
                    last_error = exc
                    if exc.status_code == 403 and output_format != formats_to_try[-1]:
                        self._logger.warning(
                            "ElevenLabs output format denied (%s); retrying with fallback",
                            output_format,
                        )
                        continue
                    raise
            if audio is None:
                if last_error is not None:
                    raise last_error
                raise RuntimeError("ElevenLabs synthesis failed without response.")
            if self._cancelled:
                return PcmAudio(data=b"", sample_rate=16000, channels=1, sample_width=2)
            pcm_bytes = b"".join(audio)
            if used_format.startswith("pcm_"):
                sample_rate = int(used_format.split("_", 1)[1])
                return PcmAudio(data=pcm_bytes, sample_rate=sample_rate, channels=1, sample_width=2)
            if used_format.startswith("wav_"):
                with wave.open(BytesIO(pcm_bytes), "rb") as wav:
                    return PcmAudio(
                        data=wav.readframes(wav.getnframes()),
                        sample_rate=wav.getframerate(),
                        channels=wav.getnchannels(),
                        sample_width=wav.getsampwidth(),
                    )
            raise RuntimeError(f"Unsupported ElevenLabs output format: {used_format}")

    async def cancel(self) -> None:
        self._cancelled = True
