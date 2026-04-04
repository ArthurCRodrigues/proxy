from __future__ import annotations

from proxy.stt.deepgram_adapter import (
    DeepgramSTTAdapter,
    _is_ws_open,
    extract_transcript,
)


def test_extract_transcript_partial() -> None:
    raw = '{"type":"Results","is_final":false,"channel":{"alternatives":[{"transcript":"hello"}]}}'
    out = extract_transcript(raw)
    assert out == ("hello", False, False)


def test_extract_transcript_final() -> None:
    raw = '{"type":"Results","is_final":true,"channel":{"alternatives":[{"transcript":"done"}]}}'
    out = extract_transcript(raw)
    assert out == ("done", True, False)


def test_extract_transcript_ignores_non_results() -> None:
    assert extract_transcript('{"type":"Metadata"}') is None
    assert extract_transcript("not json") is None
    assert (
        extract_transcript('{"type":"Results","is_final":false,"channel":{"alternatives":[{"transcript":""}]}}')
        is None
    )


def test_is_ws_open_with_closed_bool() -> None:
    class WS:
        closed = False

    assert _is_ws_open(WS())


def test_is_ws_open_with_state_string() -> None:
    class WS:
        state = "State.OPEN"

    assert _is_ws_open(WS())


def test_url_supports_keyterms_and_disable_endpointing() -> None:
    adapter = DeepgramSTTAdapter(
        api_key="k",
        sample_rate=16000,
        endpointing_enabled=False,
        utterance_end_ms=3500,
        keyterms=("prisma-infrastructure", "GitHub issue"),
    )
    url = adapter._url()
    assert "endpointing=false" in url
    assert "utterance_end_ms=3500" in url
    assert "keyterm=prisma-infrastructure" in url
    assert "keyterm=GitHub+issue" in url


def test_is_final_accumulates_segments() -> None:
    adapter = DeepgramSTTAdapter(api_key="k", sample_rate=16000)
    partials: list[str] = []
    finals: list[str] = []
    adapter.on_partial(partials.append)
    adapter.on_final(finals.append)

    # Interim partial — forwarded as partial only
    adapter._handle_message(
        '{"type":"Results","is_final":false,"speech_final":false,"channel":{"alternatives":[{"transcript":"hello world"}]}}'
    )
    assert partials == ["hello world"]
    assert finals == []

    # is_final segment — accumulated, not emitted
    adapter._handle_message(
        '{"type":"Results","is_final":true,"speech_final":false,"channel":{"alternatives":[{"transcript":"hello world"}]}}'
    )
    assert finals == []

    # Second is_final segment
    adapter._handle_message(
        '{"type":"Results","is_final":true,"speech_final":false,"channel":{"alternatives":[{"transcript":"how are you"}]}}'
    )
    assert finals == []

    # UtteranceEnd — joins and emits
    adapter._handle_message('{"type":"UtteranceEnd","channel":[0,1],"last_word_end":2.0}')
    assert finals == ["hello world how are you"]
    assert adapter._finalized_segments == []


def test_speech_final_emits_immediately() -> None:
    adapter = DeepgramSTTAdapter(api_key="k", sample_rate=16000)
    finals: list[str] = []
    adapter.on_final(finals.append)

    adapter._handle_message(
        '{"type":"Results","is_final":true,"speech_final":false,"channel":{"alternatives":[{"transcript":"first segment"}]}}'
    )
    adapter._handle_message(
        '{"type":"Results","is_final":false,"speech_final":true,"channel":{"alternatives":[{"transcript":"second segment"}]}}'
    )
    assert finals == ["first segment second segment"]


def test_utterance_end_ignored_when_no_segments() -> None:
    adapter = DeepgramSTTAdapter(api_key="k", sample_rate=16000)
    finals: list[str] = []
    adapter.on_final(finals.append)
    adapter._handle_message('{"type":"UtteranceEnd","channel":[0,1],"last_word_end":1.0}')
    assert finals == []


def test_interim_partials_not_accumulated() -> None:
    adapter = DeepgramSTTAdapter(api_key="k", sample_rate=16000)
    # Send only interim partials, no is_final
    adapter._handle_message(
        '{"type":"Results","is_final":false,"speech_final":false,"channel":{"alternatives":[{"transcript":"testing"}]}}'
    )
    assert adapter._finalized_segments == []
