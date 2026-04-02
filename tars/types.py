from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from time import time
from typing import Any
from uuid import uuid4


class EventType(str, Enum):
    WAKE = "WAKE"
    USER_SPEECH_START = "USER_SPEECH_START"
    USER_SPEECH_END = "USER_SPEECH_END"
    USER_PARTIAL = "USER_PARTIAL"
    USER_FINAL = "USER_FINAL"
    ASSISTANT_PARTIAL = "ASSISTANT_PARTIAL"
    ASSISTANT_FINAL = "ASSISTANT_FINAL"
    BARGE_IN = "BARGE_IN"
    INTERRUPT_ACK = "INTERRUPT_ACK"
    TOOL_START = "TOOL_START"
    TOOL_END = "TOOL_END"
    SESSION_EXIT = "SESSION_EXIT"
    ERROR = "ERROR"
    STOP = "STOP"
    READY = "READY"
    LISTENING_TIMEOUT = "LISTENING_TIMEOUT"
    CANCEL = "CANCEL"


class AssistantState(str, Enum):
    IDLE = "IDLE"
    WAKE_DETECTED = "WAKE_DETECTED"
    LISTENING = "LISTENING"
    THINKING = "THINKING"
    SPEAKING = "SPEAKING"
    INTERRUPTING = "INTERRUPTING"
    STOPPED = "STOPPED"


@dataclass(frozen=True)
class Event:
    type: EventType
    session_id: str | None = None
    turn_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    event_id: str = field(default_factory=lambda: str(uuid4()))
    ts: int = field(default_factory=lambda: int(time() * 1000))
