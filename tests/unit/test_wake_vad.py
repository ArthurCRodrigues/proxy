from __future__ import annotations

from proxy.audio.wake_vad import contains_wake_phrase, extract_recognizer_text


def test_contains_wake_phrase_in_text_and_partial() -> None:
    assert contains_wake_phrase('{"text":"hello proxy"}', ["proxy"])
    assert contains_wake_phrase('{"partial":"stars can you"}', ["proxy", "stars"])
    assert not contains_wake_phrase('{"text":"guitars are loud"}', ["proxy"])
    assert not contains_wake_phrase('{"text":"hello"}', ["proxy"])
    assert not contains_wake_phrase("{}", ["proxy"])
    assert not contains_wake_phrase("not json", ["proxy"])


def test_extract_recognizer_text() -> None:
    text, partial = extract_recognizer_text('{"text":"hello proxy"}')
    assert text == "hello proxy"
    assert partial == ""
    assert extract_recognizer_text("not json") == ("", "")


def test_contains_wake_phrase_partial_word_boundary() -> None:
    assert contains_wake_phrase('{"partial":"case now"}', ["case"])
    assert not contains_wake_phrase('{"partial":"showcase"}', ["case"])
