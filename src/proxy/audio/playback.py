from __future__ import annotations

import asyncio
from typing import Any

from proxy.audio.assets import PcmAudio


def _import_sounddevice() -> Any:
    try:
        import sounddevice as sd  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "sounddevice is required for audio playback. Install project dependencies first."
        ) from exc
    return sd


def split_pcm_chunks(data: bytes, bytes_per_chunk: int) -> list[bytes]:
    if bytes_per_chunk <= 0:
        raise ValueError("bytes_per_chunk must be > 0")
    return [data[i : i + bytes_per_chunk] for i in range(0, len(data), bytes_per_chunk)]


class PlaybackEngine:
    def __init__(self) -> None:
        self._stream: Any | None = None
        self._stream_rate: int = 0
        self._stream_channels: int = 0

    def _ensure_stream(self, sample_rate: int, channels: int) -> Any:
        if (
            self._stream is not None
            and self._stream_rate == sample_rate
            and self._stream_channels == channels
        ):
            return self._stream
        self._close_stream()
        sd = _import_sounddevice()
        self._stream = sd.RawOutputStream(
            samplerate=sample_rate,
            channels=channels,
            dtype="int16",
        )
        self._stream.start()
        self._stream_rate = sample_rate
        self._stream_channels = channels
        return self._stream

    def _close_stream(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
        self._stream = None
        self._stream_rate = 0
        self._stream_channels = 0

    async def play_pcm(self, audio: PcmAudio) -> None:
        stream = self._ensure_stream(audio.sample_rate, audio.channels)
        bytes_per_frame = audio.channels * audio.sample_width
        frames_per_chunk = max(1, int(audio.sample_rate * 0.02))
        bytes_per_chunk = frames_per_chunk * bytes_per_frame
        chunks = split_pcm_chunks(audio.data, bytes_per_chunk)
        for chunk in chunks:
            stream.write(chunk)
            await asyncio.sleep(0)

    async def cancel(self) -> None:
        self._close_stream()

    async def shutdown(self) -> None:
        self._close_stream()
