from __future__ import annotations

import json
from dataclasses import dataclass


@dataclass(frozen=True)
class AssistantFinalContract:
    spoken_text: str
    status: str
    raw_text: str
    contract_detected: bool


def parse_assistant_final_contract(content: str) -> AssistantFinalContract:
    raw_text = content.strip()
    if not raw_text:
        return AssistantFinalContract(
            spoken_text="",
            status="handoff",
            raw_text="",
            contract_detected=False,
        )

    lines = [line.rstrip() for line in raw_text.splitlines() if line.strip()]
    if not lines:
        return AssistantFinalContract(
            spoken_text=raw_text,
            status="handoff",
            raw_text=raw_text,
            contract_detected=False,
        )

    candidate = lines[-1].strip()
    if not (candidate.startswith("{") and candidate.endswith("}")):
        return AssistantFinalContract(
            spoken_text=raw_text,
            status="handoff",
            raw_text=raw_text,
            contract_detected=False,
        )

    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError:
        return AssistantFinalContract(
            spoken_text=raw_text,
            status="handoff",
            raw_text=raw_text,
            contract_detected=False,
        )

    status = str(payload.get("tars_status", "")).strip().lower()
    if status not in {"working", "handoff"}:
        return AssistantFinalContract(
            spoken_text=raw_text,
            status="handoff",
            raw_text=raw_text,
            contract_detected=False,
        )

    spoken_from_contract = payload.get("spoken")
    if isinstance(spoken_from_contract, str):
        spoken_text = spoken_from_contract.strip()
    else:
        spoken_text = ""
    if not spoken_text:
        spoken_text = "\n".join(lines[:-1]).strip()
    if not spoken_text:
        spoken_text = raw_text

    return AssistantFinalContract(
        spoken_text=spoken_text,
        status=status,
        raw_text=raw_text,
        contract_detected=True,
    )
