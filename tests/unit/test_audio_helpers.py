from __future__ import annotations

from pathlib import Path
import wave

import pytest

from proxy.audio.assets import load_wav_pcm
from proxy.audio.io import frames_per_chunk, normalize_input_device, resolve_input_device
from proxy.audio.playback import split_pcm_chunks


def test_frames_per_chunk() -> None:
    assert frames_per_chunk(16000, 20) == 320
    with pytest.raises(ValueError):
        frames_per_chunk(0, 20)
    with pytest.raises(ValueError):
        frames_per_chunk(16000, 0)


def test_normalize_input_device() -> None:
    assert normalize_input_device(None) is None
    assert normalize_input_device("") is None
    assert normalize_input_device("  ") is None
    assert normalize_input_device("18") == 18
    assert normalize_input_device(7) == 7
    assert normalize_input_device("default") == "default"


def test_frames_per_chunk_for_device_default_rate() -> None:
    assert frames_per_chunk(48000, 20) == 960


def test_resolve_input_device_by_substring() -> None:
    class FakeSD:
        @staticmethod
        def query_devices(device=None, kind=None):
            devices = [
                {"name": "PortAudio", "max_input_channels": 0},
                {"name": "C922 Pro Stream Webcam Analog Stereo", "max_input_channels": 2},
            ]
            if device is None:
                return devices
            return devices[int(device)]

    resolved = resolve_input_device(FakeSD(), "C922 Pro Stream Webcam")
    assert resolved == 1


def test_split_pcm_chunks() -> None:
    data = b"abcdefghij"
    chunks = split_pcm_chunks(data, 4)
    assert chunks == [b"abcd", b"efgh", b"ij"]
    with pytest.raises(ValueError):
        split_pcm_chunks(data, 0)


def test_load_wav_pcm(tmp_path: Path) -> None:
    wav_path = tmp_path / "test.wav"
    with wave.open(str(wav_path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\x00\x00" * 100)

    pcm = load_wav_pcm(wav_path)
    assert pcm.channels == 1
    assert pcm.sample_rate == 16000
    assert pcm.sample_width == 2
    assert pcm.frame_count == 100
