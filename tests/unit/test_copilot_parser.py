from __future__ import annotations

from tars.copilot.parser import parse_jsonl_event


def test_parse_delta_event() -> None:
    ev = parse_jsonl_event(
        '{"type":"assistant.message_delta","data":{"deltaContent":"hello"}}'
    )
    assert ev is not None
    assert ev.event_type == "assistant.message_delta"
    assert ev.content == "hello"


def test_parse_message_event() -> None:
    ev = parse_jsonl_event('{"type":"assistant.message","data":{"content":"done"}}')
    assert ev is not None
    assert ev.event_type == "assistant.message"
    assert ev.content == "done"


def test_parse_invalid_jsonl() -> None:
    assert parse_jsonl_event("not-json") is None
