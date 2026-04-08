from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from proxy.copilot.bridge import CopilotBridge
from proxy.observability.logger import get_logger
from proxy.orchestrator.event_bus import EventBus
from proxy.orchestrator.state_machine import (
    InvalidTransitionError,
    OrchestratorContext,
    apply_event,
)
from proxy.types import AssistantState, Event, EventType


class Orchestrator:
    def __init__(
        self,
        event_bus: EventBus,
        on_wake: Callable[[], Awaitable[None]] | None = None,
        copilot_bridge: CopilotBridge | None = None,
        on_interrupt: Callable[[], Awaitable[None]] | None = None,
        on_narration: Callable[[str], None] | None = None,
        vanguard: "LocalModelClient | None" = None,
    ) -> None:
        self._event_bus = event_bus
        self._ctx = OrchestratorContext()
        self._logger = get_logger("proxy.orchestrator")
        self._running = False
        self._on_wake = on_wake
        self._on_interrupt = on_interrupt
        self._on_narration = on_narration
        self._copilot = copilot_bridge
        self._vanguard = vanguard
        self._filler_task: asyncio.Task[None] | None = None
        self._listening_timeout_task: asyncio.Task[None] | None = None
        self._listening_timeout_ms = 10_000

    def set_listening_timeout(self, timeout_ms: int) -> None:
        self._listening_timeout_ms = max(0, timeout_ms)

    @property
    def context(self) -> OrchestratorContext:
        return self._ctx

    async def handle_event(self, event: Event) -> None:
        # Drop stale events from old turns
        if (
            event.turn_id is not None
            and event.turn_id != self._ctx.turn_id
            and event.type
            in (
                EventType.ASSISTANT_PARTIAL,
                EventType.ASSISTANT_FINAL,
                EventType.ASSISTANT_AUDIO_DONE,
            )
        ):
            self._logger.debug(
                "Dropping stale event: type=%s event_turn=%s active_turn=%s",
                event.type,
                event.turn_id,
                self._ctx.turn_id,
            )
            return

        previous_state = self._ctx.state
        try:
            new_ctx = apply_event(self._ctx, event)
        except InvalidTransitionError as exc:
            self._logger.debug(
                "Ignoring invalid transition: state=%s event=%s reason=%s",
                previous_state,
                event.type,
                exc,
            )
            return
        if new_ctx.state != previous_state:
            self._logger.info(
                "State transition: %s -> %s (event=%s)",
                previous_state,
                new_ctx.state,
                event.type,
            )
        else:
            self._logger.debug(
                "State unchanged: %s (event=%s)",
                previous_state,
                event.type,
            )
        self._ctx = new_ctx
        if previous_state != new_ctx.state:
            self._on_state_change(previous_state, new_ctx.state)
        elif new_ctx.state == AssistantState.LISTENING and event.type == EventType.USER_PARTIAL:
            self._arm_listening_timeout()

        # Side effects
        if event.type == EventType.WAKE:
            if self._on_wake is not None:
                await self._on_wake()
            await self._event_bus.publish(
                Event(
                    type=EventType.READY,
                    session_id=self._ctx.session_id,
                    turn_id=self._ctx.turn_id,
                )
            )
        if event.type == EventType.USER_FINAL and self._copilot is not None:
            text = str(event.payload.get("text", "")).strip()
            if text:
                if self._vanguard is not None:
                    self._filler_task = asyncio.create_task(
                        self._emit_latency_filler(text)
                    )
                await self._copilot.send_user_turn(text, turn_id=self._ctx.turn_id)
        if event.type == EventType.INTERRUPT:
            if self._on_interrupt is not None:
                await self._on_interrupt()

    def _on_state_change(self, previous: AssistantState, new: AssistantState) -> None:
        if new == AssistantState.LISTENING:
            self._arm_listening_timeout()
        elif previous == AssistantState.LISTENING:
            self._cancel_listening_timeout()
        if new == AssistantState.SPEAKING:
            self._cancel_filler()

    def _cancel_filler(self) -> None:
        if self._filler_task is not None and not self._filler_task.done():
            self._filler_task.cancel()
        self._filler_task = None

    async def _emit_latency_filler(self, user_text: str) -> None:
        assert self._vanguard is not None
        try:
            filler = await self._vanguard.generate_latency_filler(user_text)
            if filler and self._ctx.state == AssistantState.THINKING:
                self._logger.info("VANGUARD_FILLER: %s (narration_cb=%s)", filler, self._on_narration is not None)
                if self._on_narration is not None:
                    self._on_narration(filler)
        except asyncio.CancelledError:
            pass

    def _arm_listening_timeout(self) -> None:
        self._cancel_listening_timeout()
        if self._listening_timeout_ms <= 0:
            return
        self._listening_timeout_task = asyncio.create_task(self._listening_timeout_worker())

    def _cancel_listening_timeout(self) -> None:
        task = self._listening_timeout_task
        if task is not None and not task.done():
            task.cancel()
        self._listening_timeout_task = None

    async def _listening_timeout_worker(self) -> None:
        try:
            await asyncio.sleep(self._listening_timeout_ms / 1000.0)
            await self._event_bus.publish(Event(type=EventType.LISTENING_TIMEOUT))
        except asyncio.CancelledError:
            return

    async def run(self) -> None:
        self._running = True
        while self._running and self._ctx.state != AssistantState.STOPPED:
            event = await self._event_bus.next_event()
            try:
                await self.handle_event(event)
            finally:
                self._event_bus.task_done()
            await asyncio.sleep(0)

    def stop(self) -> None:
        self._running = False
        self._cancel_listening_timeout()
