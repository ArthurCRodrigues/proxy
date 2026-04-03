from __future__ import annotations

from proxy.stt.deepgram_adapter import (
    DeepgramSTTAdapter,
    _is_ws_open,
    _merge_partial_utterance,
    _normalize_for_compare,
    _token_overlap_count,
    _word_count,
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


def test_is_final_without_speech_final_treated_as_partial() -> None:
    adapter = DeepgramSTTAdapter(api_key="k", sample_rate=16000)
    partials: list[str] = []
    finals: list[str] = []
    adapter.on_partial(partials.append)
    adapter.on_final(finals.append)
    adapter._handle_message(
        '{"type":"Results","is_final":true,"channel":{"alternatives":[{"transcript":"hello"}]}}'
    )
    assert partials == ["hello"]
    assert finals == []


def test_speech_final_emitted_directly() -> None:
    adapter = DeepgramSTTAdapter(api_key="k", sample_rate=16000)
    finals: list[str] = []
    adapter.on_final(finals.append)
    adapter._handle_message(
        '{"type":"Results","is_final":false,"speech_final":true,"channel":{"alternatives":[{"transcript":"complete"}]}}'
    )
    assert finals == ["complete"]


def test_empty_speech_final_uses_last_partial_text() -> None:
    adapter = DeepgramSTTAdapter(api_key="k", sample_rate=16000)
    finals: list[str] = []
    adapter.on_final(finals.append)
    adapter._handle_message(
        '{"type":"Results","is_final":false,"channel":{"alternatives":[{"transcript":"working text"}]}}'
    )
    adapter._handle_message(
        '{"type":"Results","is_final":false,"speech_final":true,"channel":{"alternatives":[{"transcript":""}]}}'
    )
    assert finals == ["working text"]


def test_truncated_final_prefers_best_partial_text() -> None:
    adapter = DeepgramSTTAdapter(api_key="k", sample_rate=16000)
    finals: list[str] = []
    adapter.on_final(finals.append)
    adapter._handle_message(
        '{"type":"Results","is_final":false,"channel":{"alternatives":[{"transcript":"lets work on prisma infrastructure issue one two three"}]}}'
    )
    adapter._handle_message(
        '{"type":"Results","is_final":true,"speech_final":true,"channel":{"alternatives":[{"transcript":"issue one two three"}]}}'
    )
    assert finals == ["lets work on prisma infrastructure issue one two three"]


def test_normalize_and_word_count_helpers() -> None:
    assert _normalize_for_compare("Hello, World!") == "hello world"
    assert _word_count("a  b   c") == 3


def test_merge_partial_utterance_with_overlap() -> None:
    merged = _merge_partial_utterance(
        "I need you to answer me through the eleven labs mcp",
        "through the eleven labs mcp and just answer me through audio",
    )
    assert merged == "I need you to answer me through the eleven labs mcp and just answer me through audio"


def test_merge_partial_utterance_without_overlap_appends() -> None:
    merged = _merge_partial_utterance("first part", "second part")
    assert merged == "first part second part"


def test_token_overlap_count_detects_suffix_prefix_overlap() -> None:
    overlap = _token_overlap_count("alpha beta gamma delta", "gamma delta epsilon zeta")
    assert overlap == 2
