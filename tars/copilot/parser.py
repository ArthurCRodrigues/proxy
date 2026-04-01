from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ParsedCopilotEvent:
    event_type: str
    content: str | None = None
    raw: dict[str, Any] | None = None


def extract_text_line(raw: str) -> str:
    return raw.strip()


def parse_jsonl_event(line: str) -> ParsedCopilotEvent | None:
    text = line.strip()
    if not text:
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None

    event_type = str(payload.get("type", ""))
    data = payload.get("data", {})

    if event_type == "assistant.message_delta":
        delta = str(data.get("deltaContent", "")).strip()
        return ParsedCopilotEvent(event_type=event_type, content=delta, raw=payload)
    if event_type == "assistant.message":
        content = str(data.get("content", "")).strip()
        return ParsedCopilotEvent(event_type=event_type, content=content, raw=payload)

    return ParsedCopilotEvent(event_type=event_type, content=None, raw=payload)
