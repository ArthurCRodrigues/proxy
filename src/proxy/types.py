from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from time import time
from typing import Any
from uuid import uuid4


class EventType(str, Enum):
    WAKE = "WAKE"
    USER_PARTIAL = "USER_PARTIAL"
    USER_FINAL = "USER_FINAL"
    ASSISTANT_PARTIAL = "ASSISTANT_PARTIAL"
    ASSISTANT_FINAL = "ASSISTANT_FINAL"
    ASSISTANT_AUDIO_DONE = "ASSISTANT_AUDIO_DONE"
    ERROR = "ERROR"
    STOP = "STOP"
    READY = "READY"
    LISTENING_TIMEOUT = "LISTENING_TIMEOUT"
    CANCEL = "CANCEL"
    INTERRUPT = "INTERRUPT"
    STATUS_REQUEST = "STATUS_REQUEST"


class AssistantState(str, Enum):
    IDLE = "IDLE"
    WAKE_DETECTED = "WAKE_DETECTED"
    LISTENING = "LISTENING"
    THINKING = "THINKING"
    SPEAKING = "SPEAKING"
    STOPPED = "STOPPED"


@dataclass(frozen=True)
class Event:
    type: EventType
    session_id: str | None = None
    turn_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    event_id: str = field(default_factory=lambda: str(uuid4()))
    ts: int = field(default_factory=lambda: int(time() * 1000))
