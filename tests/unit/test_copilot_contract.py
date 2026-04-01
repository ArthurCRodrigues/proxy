from __future__ import annotations

from tars.copilot.contract import parse_assistant_final_contract


def test_parse_contract_handoff_last_line_json() -> None:
    text = (
        "Done. I updated the pipeline and tests.\n"
        '{"tars_status":"handoff","spoken":"Done. I updated the pipeline and tests."}'
    )
    parsed = parse_assistant_final_contract(text)
    assert parsed.contract_detected is True
    assert parsed.status == "handoff"
    assert parsed.spoken_text == "Done. I updated the pipeline and tests."


def test_parse_contract_working_status() -> None:
    text = '{"tars_status":"working","spoken":"I am searching through it now."}'
    parsed = parse_assistant_final_contract(text)
    assert parsed.contract_detected is True
    assert parsed.status == "working"
    assert parsed.spoken_text == "I am searching through it now."


def test_parse_contract_fallback_without_json() -> None:
    text = "I finished your request."
    parsed = parse_assistant_final_contract(text)
    assert parsed.contract_detected is False
    assert parsed.status == "handoff"
    assert parsed.spoken_text == "I finished your request."
