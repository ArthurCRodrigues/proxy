from __future__ import annotations

import asyncio

from tars.orchestrator.event_bus import EventBus
from tars.types import Event, EventType


def test_event_bus_round_trip() -> None:
    async def _run() -> None:
        bus = EventBus(maxsize=4)
        event = Event(type=EventType.WAKE)
        await bus.publish(event)

        out = await bus.next_event()
        assert out == event
        bus.task_done()

    asyncio.run(_run())
