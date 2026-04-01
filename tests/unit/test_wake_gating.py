from __future__ import annotations

from types import SimpleNamespace

from tars.audio.wake_vad import WakeVadEngine


def test_wake_should_trigger_disabled() -> None:
    engine = WakeVadEngine(
        event_bus=None,  # type: ignore[arg-type]
        audio_io=None,  # type: ignore[arg-type]
        sample_rate=16000,
        wake_phrase="case",
        wake_aliases="case",
        vosk_model_path="assets/models/vosk-model-small-en-us-0.15",
        wake_enabled=lambda: False,
    )
    assert engine._wake_should_trigger() is False


def test_wake_should_trigger_enabled() -> None:
    engine = WakeVadEngine(
        event_bus=None,  # type: ignore[arg-type]
        audio_io=None,  # type: ignore[arg-type]
        sample_rate=16000,
        wake_phrase="case",
        wake_aliases="case",
        vosk_model_path="assets/models/vosk-model-small-en-us-0.15",
        wake_enabled=lambda: True,
    )
    assert engine._wake_should_trigger() is True


def test_wake_latch_allows_single_trigger_per_idle_cycle() -> None:
    idle = True

    engine = WakeVadEngine(
        event_bus=None,  # type: ignore[arg-type]
        audio_io=None,  # type: ignore[arg-type]
        sample_rate=16000,
        wake_phrase="case",
        wake_aliases="case",
        vosk_model_path="assets/models/vosk-model-small-en-us-0.15",
        wake_enabled=lambda: idle,
        wake_rearm_guard_ms=0,
    )
    assert engine._wake_should_trigger() is True

    engine._wake_armed = False
    assert engine._wake_should_trigger() is False

    idle = False
    assert engine._wake_should_trigger() is False

    idle = True
    assert engine._wake_should_trigger() is True


def test_wake_rearm_guard_blocks_immediate_idle_retrigger() -> None:
    idle = False
    engine = WakeVadEngine(
        event_bus=None,  # type: ignore[arg-type]
        audio_io=None,  # type: ignore[arg-type]
        sample_rate=16000,
        wake_phrase="case",
        wake_aliases="case",
        vosk_model_path="assets/models/vosk-model-small-en-us-0.15",
        wake_enabled=lambda: idle,
        wake_rearm_guard_ms=10_000,
    )

    # Leave idle -> returns false and rearms.
    assert engine._wake_should_trigger() is False
    idle = True
    # Immediate return to idle is blocked by guard window.
    assert engine._wake_should_trigger() is False


def test_partial_wake_match_disabled_by_default() -> None:
    engine = WakeVadEngine(
        event_bus=None,  # type: ignore[arg-type]
        audio_io=None,  # type: ignore[arg-type]
        sample_rate=16000,
        wake_phrase="case",
        wake_aliases="case",
        vosk_model_path="assets/models/vosk-model-small-en-us-0.15",
        wake_match_partial=False,
    )
    assert engine._wake_match_partial is False


def test_wake_state_boundary_resets_recognizer_and_vad() -> None:
    idle = True
    engine = WakeVadEngine(
        event_bus=None,  # type: ignore[arg-type]
        audio_io=None,  # type: ignore[arg-type]
        sample_rate=16000,
        wake_phrase="case",
        wake_aliases="case",
        vosk_model_path="assets/models/vosk-model-small-en-us-0.15",
        wake_enabled=lambda: idle,
    )
    reset_count = 0

    def _reset() -> None:
        nonlocal reset_count
        reset_count += 1

    engine._recognizer = SimpleNamespace(Reset=_reset)  # type: ignore[assignment]
    engine._vad.speech_active = True
    engine._vad.silence_ms = 100

    assert engine._wake_should_trigger() is True
    assert reset_count == 1
    assert engine._vad.speech_active is False
    assert engine._vad.silence_ms == 0

    idle = False
    assert engine._wake_should_trigger() is False
    assert reset_count == 2
