from __future__ import annotations

import asyncio

from proxy.orchestrator.engine import Orchestrator
from proxy.orchestrator.event_bus import EventBus
from proxy.types import AssistantState, Event, EventType


def test_listening_timeout_resets_on_speech_activity() -> None:
    async def _run() -> None:
        bus = EventBus()
        orchestrator = Orchestrator(bus)
        orchestrator.set_listening_timeout(200)

        await orchestrator.handle_event(Event(type=EventType.WAKE))
        ready = await bus.next_event()
        assert ready.type == EventType.READY
        bus.task_done()
        await orchestrator.handle_event(ready)
        assert orchestrator.context.state == AssistantState.LISTENING

        await asyncio.sleep(0.12)
        await orchestrator.handle_event(Event(type=EventType.USER_PARTIAL, payload={"text": "hello"}))
        assert orchestrator.context.state == AssistantState.LISTENING

        await asyncio.sleep(0.12)
        assert orchestrator.context.state == AssistantState.LISTENING

        await asyncio.sleep(0.12)
        event = await bus.next_event()
        assert event.type == EventType.LISTENING_TIMEOUT
        bus.task_done()

        await orchestrator.handle_event(event)
        assert orchestrator.context.state == AssistantState.IDLE
        orchestrator.stop()

    asyncio.run(_run())
