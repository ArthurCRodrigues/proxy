from __future__ import annotations

import asyncio
from typing import Any


def frames_per_chunk(sample_rate: int, chunk_ms: int) -> int:
    if sample_rate <= 0:
        raise ValueError("sample_rate must be > 0")
    if chunk_ms <= 0:
        raise ValueError("chunk_ms must be > 0")
    return max(1, int(sample_rate * (chunk_ms / 1000.0)))


def _import_sounddevice() -> Any:
    try:
        import sounddevice as sd  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "sounddevice is required for audio capture. Install project dependencies first."
        ) from exc
    return sd


def normalize_input_device(input_device: str | int | None) -> str | int | None:
    if input_device is None:
        return None
    if isinstance(input_device, int):
        return input_device
    value = input_device.strip()
    if not value:
        return None
    if value.isdigit():
        return int(value)
    return value


def resolve_input_device(sd: Any, input_device: str | int | None) -> int | None:
    device = normalize_input_device(input_device)
    if device is None:
        return None
    if isinstance(device, int):
        info = sd.query_devices(device)
        if int(info.get("max_input_channels", 0)) <= 0:
            raise ValueError(f"Configured device index {device} is not an input device")
        return device

    input_devices: list[tuple[int, str]] = []
    for idx, info in enumerate(sd.query_devices()):
        if int(info.get("max_input_channels", 0)) > 0:
            input_devices.append((idx, str(info.get("name", ""))))

    target = device.lower()
    for idx, name in input_devices:
        if name.lower() == target:
            return idx
    for idx, name in input_devices:
        if target in name.lower():
            return idx

    available = ", ".join(f"{idx}:{name}" for idx, name in input_devices)
    raise ValueError(f"No input device matching '{device}'. Available input devices: {available}")


class AudioIO:
    def __init__(
        self,
        sample_rate: int = 16000,
        channels: int = 1,
        chunk_ms: int = 20,
        queue_maxsize: int = 128,
        input_device: str | int | None = None,
    ) -> None:
        self.sample_rate = sample_rate
        self.channels = channels
        self.chunk_ms = chunk_ms
        self.blocksize_frames = frames_per_chunk(sample_rate, chunk_ms)
        self.input_device = normalize_input_device(input_device)
        self._queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=queue_maxsize)
        self._stream: Any | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._running = False
        self.actual_sample_rate = sample_rate
        self.resolved_input_device: int | None = None

    @property
    def running(self) -> bool:
        return self._running

    def _enqueue_chunk(self, chunk: bytes) -> None:
        if self._queue.full():
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        self._queue.put_nowait(chunk)

    def start(self, loop: asyncio.AbstractEventLoop | None = None) -> None:
        if self._running:
            return
        sd = _import_sounddevice()
        self._loop = loop
        self.resolved_input_device = resolve_input_device(sd, self.input_device)

        def callback(indata: Any, _frames: int, _time_info: Any, _status: Any) -> None:
            payload = bytes(indata)
            if self._loop is not None and self._loop.is_running():
                self._loop.call_soon_threadsafe(self._enqueue_chunk, payload)
            else:
                self._enqueue_chunk(payload)

        device = self.resolved_input_device
        effective_sr = self.sample_rate
        try:
            self._stream = sd.RawInputStream(
                samplerate=self.sample_rate,
                channels=self.channels,
                dtype="int16",
                blocksize=self.blocksize_frames,
                device=device,
                callback=callback,
            )
        except Exception as exc:
            message = str(exc).lower()
            if "invalid sample rate" not in message:
                raise
            device_info = sd.query_devices(device=device, kind="input")
            effective_sr = int(device_info["default_samplerate"])
            self.blocksize_frames = frames_per_chunk(effective_sr, self.chunk_ms)
            self._stream = sd.RawInputStream(
                samplerate=effective_sr,
                channels=self.channels,
                dtype="int16",
                blocksize=self.blocksize_frames,
                device=device,
                callback=callback,
            )

        self.actual_sample_rate = effective_sr
        self._stream.start()
        self._running = True

    def stop(self) -> None:
        if not self._running:
            return
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        self._running = False

    async def read_chunk(self, timeout_s: float | None = None) -> bytes:
        if timeout_s is None:
            return await self._queue.get()
        return await asyncio.wait_for(self._queue.get(), timeout=timeout_s)
