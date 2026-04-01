from __future__ import annotations

import asyncio

import pytest

from tars.tts.elevenlabs_adapter import ElevenLabsTTSAdapter


def test_synthesize_text_requires_api_key() -> None:
    adapter = ElevenLabsTTSAdapter(api_key="", voice_id="voice")
    with pytest.raises(RuntimeError):
        asyncio.run(adapter.synthesize_text("hello"))


def test_synthesize_text_requires_voice_id() -> None:
    adapter = ElevenLabsTTSAdapter(api_key="key", voice_id="")
    with pytest.raises(RuntimeError):
        asyncio.run(adapter.synthesize_text("hello"))


def test_synthesize_text_empty_returns_empty_pcm() -> None:
    adapter = ElevenLabsTTSAdapter(api_key="key", voice_id="voice")
    pcm = asyncio.run(adapter.synthesize_text("   "))
    assert pcm.data == b""
    assert pcm.sample_rate == 16000
    assert pcm.channels == 1
    assert pcm.sample_width == 2


def test_cancel_sets_flag() -> None:
    adapter = ElevenLabsTTSAdapter(api_key="key", voice_id="voice")
    asyncio.run(adapter.cancel())
    assert adapter._cancelled is True


def test_adapter_defaults_to_quality_profile() -> None:
    adapter = ElevenLabsTTSAdapter(api_key="key", voice_id="voice")
    assert adapter._model_id == "eleven_multilingual_v2"
    assert adapter._output_format == "pcm_22050"
    assert adapter._fallback_output_formats == ("wav_22050",)
    assert adapter._stability == 0.45
    assert adapter._similarity_boost == 0.85
    assert adapter._style == 0.25
    assert adapter._speed == 0.95
    assert adapter._use_speaker_boost is True
