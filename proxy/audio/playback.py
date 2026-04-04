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
        self._play_task: asyncio.Task[None] | None = None
        self._stream_task: asyncio.Task[None] | None = None
        self._audio_queue: asyncio.Queue[bytes | None] | None = None
        self._stream_lock = asyncio.Lock()
        self._stream_channels = 1

    async def play_pcm(self, audio: PcmAudio) -> None:
        await self.cancel()
        self._play_task = asyncio.create_task(self._play_worker(audio))
        await self._play_task

    async def _play_worker(self, audio: PcmAudio) -> None:
        sd = _import_sounddevice()
        bytes_per_frame = audio.channels * audio.sample_width
        frames_per_chunk = max(1, int(audio.sample_rate * 0.02))
        bytes_per_chunk = frames_per_chunk * bytes_per_frame
        chunks = split_pcm_chunks(audio.data, bytes_per_chunk)

        stream = sd.RawOutputStream(
            samplerate=audio.sample_rate,
            channels=audio.channels,
            dtype="int16",
        )
        stream.start()
        try:
            for chunk in chunks:
                stream.write(chunk)
                await asyncio.sleep(0)
        finally:
            stream.stop()
            stream.close()

    async def start_stream(
        self,
        sample_rate: int = 22050,
        channels: int = 1,
        queue_maxsize: int = 256,
    ) -> None:
        async with self._stream_lock:
            await self._cancel_stream_locked()
            self._stream_channels = channels
            self._audio_queue = asyncio.Queue(maxsize=max(1, queue_maxsize))
            self._stream_task = asyncio.create_task(
                self._stream_worker(sample_rate, channels)
            )

    async def push_audio(self, data: bytes) -> None:
        if not data:
            return
        queue = self._audio_queue
        if queue is None:
            return
        if len(data) % (self._stream_channels * 2) != 0:
            data = self._trim_to_frame_boundary(data, self._stream_channels)
        if not data:
            return
        try:
            queue.put_nowait(data)
        except asyncio.QueueFull as exc:
            raise RuntimeError("Playback stream queue is full") from exc

    async def end_stream(self) -> None:
        async with self._stream_lock:
            queue = self._audio_queue
            stream_task = self._stream_task
            if queue is not None:
                await queue.put(None)
            if stream_task is not None and not stream_task.done():
                await stream_task
            self._stream_task = None
            self._audio_queue = None

    async def _stream_worker(self, sample_rate: int, channels: int) -> None:
        sd = _import_sounddevice()
        stream = sd.RawOutputStream(
            samplerate=sample_rate,
            channels=channels,
            dtype="int16",
        )
        stream.start()
        try:
            assert self._audio_queue is not None
            while True:
                chunk = await self._audio_queue.get()
                if chunk is None:
                    break
                stream.write(chunk)
                await asyncio.sleep(0)
        finally:
            stream.stop()
            stream.close()

    async def cancel(self) -> None:
        if self._play_task is not None:
            if not self._play_task.done():
                self._play_task.cancel()
                try:
                    await self._play_task
                except asyncio.CancelledError:
                    pass
            self._play_task = None
        async with self._stream_lock:
            await self._cancel_stream_locked()

    async def _cancel_stream_locked(self) -> None:
        if self._stream_task is not None:
            if not self._stream_task.done():
                self._stream_task.cancel()
                try:
                    await self._stream_task
                except asyncio.CancelledError:
                    pass
            self._stream_task = None
        self._audio_queue = None

    @staticmethod
    def _trim_to_frame_boundary(data: bytes, channels: int) -> bytes:
        bytes_per_frame = channels * 2
        if bytes_per_frame <= 0:
            return b""
        usable_len = len(data) - (len(data) % bytes_per_frame)
        return data[:usable_len]
