from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from tars.types import AssistantState, Event, EventType


@dataclass
class OrchestratorContext:
    state: AssistantState = AssistantState.IDLE
    session_id: str | None = None
    turn_id: str | None = None


class InvalidTransitionError(ValueError):
    pass


def _new_id() -> str:
    return str(uuid4())


def apply_event(ctx: OrchestratorContext, event: Event) -> OrchestratorContext:
    state = ctx.state

    if event.type == EventType.STOP:
        return OrchestratorContext(
            state=AssistantState.STOPPED,
            session_id=ctx.session_id,
            turn_id=ctx.turn_id,
        )
    if event.type in (
        EventType.SESSION_EXIT,
        EventType.TOOL_START,
        EventType.TOOL_END,
        EventType.CONTINUE_TURN,
    ):
        return ctx
    if event.type in (EventType.USER_SPEECH_START, EventType.USER_SPEECH_END, EventType.USER_PARTIAL):
        return ctx

    if state == AssistantState.IDLE:
        if event.type == EventType.WAKE:
            return OrchestratorContext(
                state=AssistantState.WAKE_DETECTED,
                session_id=_new_id(),
                turn_id=None,
            )
        raise InvalidTransitionError(f"{state} cannot handle {event.type}")

    if state == AssistantState.WAKE_DETECTED:
        if event.type == EventType.READY:
            return OrchestratorContext(
                state=AssistantState.LISTENING,
                session_id=ctx.session_id,
                turn_id=_new_id(),
            )
        raise InvalidTransitionError(f"{state} cannot handle {event.type}")

    if state == AssistantState.LISTENING:
        if event.type in (EventType.CANCEL, EventType.LISTENING_TIMEOUT):
            return OrchestratorContext(
                state=AssistantState.IDLE,
                session_id=None,
                turn_id=None,
            )
        if event.type == EventType.USER_FINAL:
            return OrchestratorContext(
                state=AssistantState.THINKING,
                session_id=ctx.session_id,
                turn_id=ctx.turn_id or _new_id(),
            )
        if event.type == EventType.BARGE_IN:
            return ctx
        raise InvalidTransitionError(f"{state} cannot handle {event.type}")

    if state == AssistantState.THINKING:
        if event.type == EventType.ASSISTANT_FINAL:
            status = str(event.payload.get("status", "handoff")).strip().lower()
            if status == "working":
                return OrchestratorContext(
                    state=AssistantState.THINKING,
                    session_id=ctx.session_id,
                    turn_id=ctx.turn_id,
                )
            return OrchestratorContext(
                state=AssistantState.IDLE,
                session_id=None,
                turn_id=None,
            )
        if event.type == EventType.ASSISTANT_PARTIAL:
            return OrchestratorContext(
                state=AssistantState.SPEAKING,
                session_id=ctx.session_id,
                turn_id=ctx.turn_id,
            )
        if event.type == EventType.BARGE_IN:
            return OrchestratorContext(
                state=AssistantState.INTERRUPTING,
                session_id=ctx.session_id,
                turn_id=ctx.turn_id,
            )
        raise InvalidTransitionError(f"{state} cannot handle {event.type}")

    if state == AssistantState.SPEAKING:
        if event.type == EventType.ASSISTANT_PARTIAL:
            return ctx
        if event.type == EventType.ASSISTANT_FINAL:
            status = str(event.payload.get("status", "handoff")).strip().lower()
            if status == "working":
                return OrchestratorContext(
                    state=AssistantState.THINKING,
                    session_id=ctx.session_id,
                    turn_id=ctx.turn_id,
                )
            return OrchestratorContext(
                state=AssistantState.IDLE,
                session_id=None,
                turn_id=None,
            )
        if event.type == EventType.BARGE_IN:
            return OrchestratorContext(
                state=AssistantState.INTERRUPTING,
                session_id=ctx.session_id,
                turn_id=ctx.turn_id,
            )
        raise InvalidTransitionError(f"{state} cannot handle {event.type}")

    if state == AssistantState.INTERRUPTING:
        if event.type == EventType.INTERRUPT_ACK:
            return OrchestratorContext(
                state=AssistantState.LISTENING,
                session_id=ctx.session_id,
                turn_id=_new_id(),
            )
        raise InvalidTransitionError(f"{state} cannot handle {event.type}")

    if state == AssistantState.STOPPED:
        raise InvalidTransitionError(f"{state} cannot handle {event.type}")

    raise InvalidTransitionError(f"Unsupported state {state}")
