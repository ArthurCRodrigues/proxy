from __future__ import annotations

from pathlib import Path
import wave

from tars.audio.assets import choose_wake_sound, list_wake_wavs


def _write_wav(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\x00\x00" * 10)


def test_list_wake_wavs_empty(tmp_path: Path) -> None:
    sounds_dir = tmp_path / "wake"
    assert list_wake_wavs(str(sounds_dir)) == []


def test_choose_wake_sound_falls_back(tmp_path: Path) -> None:
    fallback = tmp_path / "yes.wav"
    _write_wav(fallback)
    picked = choose_wake_sound(str(tmp_path / "wake"), str(fallback))
    assert picked == fallback


def test_choose_wake_sound_from_candidates(tmp_path: Path) -> None:
    sounds_dir = tmp_path / "wake"
    a = sounds_dir / "a.wav"
    b = sounds_dir / "b.wav"
    _write_wav(a)
    _write_wav(b)
    fallback = tmp_path / "yes.wav"
    _write_wav(fallback)

    picked = choose_wake_sound(str(sounds_dir), str(fallback))
    assert picked in {a, b}
