from __future__ import annotations

import pytest

from tars.orchestrator.state_machine import (
    InvalidTransitionError,
    OrchestratorContext,
    apply_event,
)
from tars.types import AssistantState, Event, EventType


def test_happy_path_transitions() -> None:
    ctx = OrchestratorContext()
    ctx = apply_event(ctx, Event(type=EventType.WAKE))
    assert ctx.state == AssistantState.WAKE_DETECTED
    assert ctx.session_id is not None

    ctx = apply_event(ctx, Event(type=EventType.READY))
    assert ctx.state == AssistantState.LISTENING
    assert ctx.turn_id is not None

    ctx = apply_event(ctx, Event(type=EventType.USER_FINAL))
    assert ctx.state == AssistantState.THINKING

    ctx = apply_event(ctx, Event(type=EventType.ASSISTANT_PARTIAL))
    assert ctx.state == AssistantState.SPEAKING

    ctx = apply_event(ctx, Event(type=EventType.ASSISTANT_FINAL))
    assert ctx.state == AssistantState.IDLE
    assert ctx.session_id is None


def test_barge_in_interrupt_flow() -> None:
    ctx = OrchestratorContext(state=AssistantState.THINKING, session_id="s", turn_id="t")
    ctx = apply_event(ctx, Event(type=EventType.BARGE_IN))
    assert ctx.state == AssistantState.INTERRUPTING

    ctx = apply_event(ctx, Event(type=EventType.INTERRUPT_ACK))
    assert ctx.state == AssistantState.LISTENING
    assert ctx.turn_id is not None
    assert ctx.turn_id != "t"


def test_invalid_transition_raises() -> None:
    with pytest.raises(InvalidTransitionError):
        apply_event(OrchestratorContext(), Event(type=EventType.USER_FINAL))


def test_listening_accepts_speech_start_end_without_state_change() -> None:
    ctx = OrchestratorContext(state=AssistantState.LISTENING, session_id="s", turn_id="t")
    out = apply_event(ctx, Event(type=EventType.USER_SPEECH_START))
    assert out == ctx
    out = apply_event(ctx, Event(type=EventType.USER_SPEECH_END))
    assert out == ctx


def test_idle_accepts_speech_and_partial_without_state_change() -> None:
    ctx = OrchestratorContext(state=AssistantState.IDLE)
    out = apply_event(ctx, Event(type=EventType.USER_SPEECH_START))
    assert out == ctx
    out = apply_event(ctx, Event(type=EventType.USER_SPEECH_END))
    assert out == ctx
    out = apply_event(ctx, Event(type=EventType.USER_PARTIAL))
    assert out == ctx


def test_speaking_accepts_assistant_partial_without_state_change() -> None:
    ctx = OrchestratorContext(state=AssistantState.SPEAKING, session_id="s", turn_id="t")
    out = apply_event(ctx, Event(type=EventType.ASSISTANT_PARTIAL))
    assert out == ctx


def test_stop_is_global_transition() -> None:
    for state in AssistantState:
        if state == AssistantState.STOPPED:
            continue
        ctx = OrchestratorContext(state=state)
        out = apply_event(ctx, Event(type=EventType.STOP))
        assert out.state == AssistantState.STOPPED


def test_listening_timeout_returns_to_idle() -> None:
    ctx = OrchestratorContext(state=AssistantState.LISTENING, session_id="s", turn_id="t")
    out = apply_event(ctx, Event(type=EventType.LISTENING_TIMEOUT))
    assert out.state == AssistantState.IDLE
    assert out.session_id is None
    assert out.turn_id is None


def test_cancel_returns_to_idle_without_thinking() -> None:
    ctx = OrchestratorContext(state=AssistantState.LISTENING, session_id="s", turn_id="t")
    out = apply_event(ctx, Event(type=EventType.CANCEL))
    assert out.state == AssistantState.IDLE
    assert out.session_id is None
    assert out.turn_id is None

def test_assistant_final_returns_to_idle() -> None:
    ctx = OrchestratorContext(state=AssistantState.THINKING, session_id="s", turn_id="t")
    out = apply_event(ctx, Event(type=EventType.ASSISTANT_FINAL))
    assert out.state == AssistantState.IDLE
    assert out.session_id is None
    assert out.turn_id is None
