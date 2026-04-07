from __future__ import annotations

import asyncio

from proxy.types import Event


class EventBus:
    def __init__(self, maxsize: int = 256) -> None:
        self._queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=maxsize)

    async def publish(self, event: Event) -> None:
        await self._queue.put(event)

    async def next_event(self) -> Event:
        return await self._queue.get()

    def task_done(self) -> None:
        self._queue.task_done()
