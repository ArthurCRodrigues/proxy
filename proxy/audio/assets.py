from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import random
import wave


PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class PcmAudio:
    data: bytes
    sample_rate: int
    channels: int
    sample_width: int

    @property
    def frame_count(self) -> int:
        bytes_per_frame = self.channels * self.sample_width
        return len(self.data) // bytes_per_frame


def resolve_asset_path(asset_path: str) -> Path:
    path = Path(asset_path)
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


def load_wav_pcm(path: Path) -> PcmAudio:
    with wave.open(str(path), "rb") as wav:
        sample_width = wav.getsampwidth()
        channels = wav.getnchannels()
        sample_rate = wav.getframerate()
        data = wav.readframes(wav.getnframes())

    if sample_width != 2:
        raise ValueError(f"Unsupported sample width {sample_width}, expected 2 (PCM16)")

    return PcmAudio(
        data=data,
        sample_rate=sample_rate,
        channels=channels,
        sample_width=sample_width,
    )


def list_wake_wavs(wake_sounds_dir: str) -> list[Path]:
    directory = resolve_asset_path(wake_sounds_dir)
    if not directory.exists() or not directory.is_dir():
        return []
    return sorted(p for p in directory.rglob("*.wav") if p.is_file())


def choose_wake_sound(wake_sounds_dir: str, fallback_asset_path: str) -> Path:
    candidates = list_wake_wavs(wake_sounds_dir)
    if candidates:
        return random.choice(candidates)
    return resolve_asset_path(fallback_asset_path)


def load_random_wake_audio(wake_sounds_dir: str, fallback_asset_path: str) -> PcmAudio:
    return load_wav_pcm(choose_wake_sound(wake_sounds_dir, fallback_asset_path))
