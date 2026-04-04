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
        latency_mode="optimistic",
    )
    url = adapter._url()
    assert "abc123" in url
    assert "eleven_flash_v2_5" in url
    assert "pcm_22050" in url
    assert "latency_mode=optimistic" in url


def test_cancel_closes_cleanly() -> None:
    import asyncio
    adapter = ElevenLabsTTSAdapter(api_key="key", voice_id="voice")
    asyncio.run(adapter.cancel())
    assert adapter._ws is None


def test_legacy_methods_delegate_to_stream_methods() -> None:
    import asyncio

    events: list[str] = []

    class FakeAdapter(ElevenLabsTTSAdapter):
        async def start_stream(self) -> None:  # type: ignore[override]
            events.append("start")

        async def push_text(self, text: str) -> None:  # type: ignore[override]
            events.append(f"push:{text}")

        async def finalize_stream(self) -> None:  # type: ignore[override]
            events.append("finalize")

        async def cancel_stream(self) -> None:  # type: ignore[override]
            events.append("cancel")

    adapter = FakeAdapter(api_key="key", voice_id="voice")
    asyncio.run(adapter.connect())
    asyncio.run(adapter.send_text("hello"))
    asyncio.run(adapter.flush())
    asyncio.run(adapter.cancel())

    assert events == ["start", "push:hello", "finalize", "cancel"]
