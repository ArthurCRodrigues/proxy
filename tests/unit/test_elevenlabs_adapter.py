from __future__ import annotations

import pytest

from proxy.tts.elevenlabs_adapter import ElevenLabsTTSAdapter


def test_adapter_requires_api_key() -> None:
    adapter = ElevenLabsTTSAdapter(api_key="", voice_id="voice")
    with pytest.raises(RuntimeError, match="API key"):
        import asyncio
        asyncio.run(adapter.connect())


def test_adapter_requires_voice_id() -> None:
    adapter = ElevenLabsTTSAdapter(api_key="key", voice_id="")
    with pytest.raises(RuntimeError, match="voice ID"):
        import asyncio
        asyncio.run(adapter.connect())


def test_url_contains_voice_and_model() -> None:
    adapter = ElevenLabsTTSAdapter(
        api_key="key",
        voice_id="abc123",
        model_id="eleven_flash_v2_5",
        output_format="pcm_22050",
    )
    url = adapter._url()
    assert "abc123" in url
    assert "eleven_flash_v2_5" in url
    assert "pcm_22050" in url


def test_cancel_closes_cleanly() -> None:
    import asyncio
    adapter = ElevenLabsTTSAdapter(api_key="key", voice_id="voice")
    asyncio.run(adapter.cancel())
    assert adapter._ws is None
