from __future__ import annotations

from tars.audio.wake_vad import VADTracker, contains_wake_phrase, extract_recognizer_text


def test_contains_wake_phrase_in_text_and_partial() -> None:
    assert contains_wake_phrase('{"text":"hello tars"}', ["tars"])
    assert contains_wake_phrase('{"partial":"stars can you"}', ["tars", "stars"])
    assert not contains_wake_phrase('{"text":"guitars are loud"}', ["tars"])
    assert not contains_wake_phrase('{"text":"hello"}', ["tars"])
    assert not contains_wake_phrase("{}", ["tars"])
    assert not contains_wake_phrase("not json", ["tars"])


def test_vad_tracker_start_and_end() -> None:
    vad = VADTracker(start_rms=600.0, end_rms=350.0, end_silence_ms=60)

    start, end = vad.step(rms=700.0, chunk_ms=20)
    assert start is True
    assert end is False
    assert vad.speech_active is True

    start, end = vad.step(rms=200.0, chunk_ms=20)
    assert (start, end) == (False, False)
    assert vad.speech_active is True

    start, end = vad.step(rms=200.0, chunk_ms=20)
    assert (start, end) == (False, False)
    assert vad.speech_active is True

    start, end = vad.step(rms=200.0, chunk_ms=20)
    assert (start, end) == (False, True)
    assert vad.speech_active is False


def test_extract_recognizer_text() -> None:
    text, partial = extract_recognizer_text('{"text":"hello tars"}')
    assert text == "hello tars"
    assert partial == ""
    assert extract_recognizer_text("not json") == ("", "")


def test_contains_wake_phrase_partial_word_boundary() -> None:
    assert contains_wake_phrase('{"partial":"case now"}', ["case"])
    assert not contains_wake_phrase('{"partial":"showcase"}', ["case"])
