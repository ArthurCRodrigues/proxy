from __future__ import annotations

from tars.tts.chunking import (
    append_partial,
    consume_speakable_segments,
    merge_final,
    split_speakable_segments,
)


def test_append_partial() -> None:
    assert append_partial("", "Hello") == "Hello"
    assert append_partial("Hello", " world") == "Hello world"


def test_split_speakable_segments_boundary() -> None:
    segments, rest = split_speakable_segments("Hello world. Next part", force=False, min_chars=5)
    assert segments == ["Hello world."]
    assert rest == "Next part"


def test_split_speakable_segments_force_flush() -> None:
    segments, rest = split_speakable_segments("No boundary text", force=True, min_chars=50)
    assert segments == ["No boundary text"]
    assert rest == ""


def test_consume_speakable_segments_reports_consumed_chars() -> None:
    segments, rest, consumed = consume_speakable_segments(
        "Hello world. Next part",
        force=False,
        min_chars=5,
    )
    assert segments == ["Hello world."]
    assert rest == "Next part"
    assert consumed == len("Hello world. ")


def test_split_speakable_segments_force_flush_chars_tuning() -> None:
    text = "A" * 30
    segments, rest = split_speakable_segments(
        text,
        force=False,
        min_chars=10,
        force_flush_chars=20,
    )
    assert segments == [text]
    assert rest == ""


def test_merge_final_prefers_buffer_when_final_subset() -> None:
    merged = merge_final(
        "I need you to answer me through the eleven labs mcp",
        "eleven labs mcp",
    )
    assert merged == "I need you to answer me through the eleven labs mcp"


def test_merge_final_prefers_final_when_superset() -> None:
    merged = merge_final("short phrase", "This is a short phrase with more detail")
    assert merged == "This is a short phrase with more detail"
