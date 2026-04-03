from __future__ import annotations

from proxy.stt.filtering import EchoFilter, SpeechGate, normalize_text


def test_normalize_text() -> None:
    assert normalize_text("  Hello   World ") == "hello world"


def test_echo_filter_matches_recent_text() -> None:
    filt = EchoFilter(similarity_threshold=0.75, window_seconds=10)
    filt.record_assistant_text("yes how can i help")
    assert filt.is_echo("yes how can i help")
    assert filt.is_echo("yes how can help")
    assert not filt.is_echo("open the repository")


def test_speech_gate_blocks_then_allows() -> None:
    gate = SpeechGate(hold_ms=1)
    gate.block()
    assert gate.allow() is False
