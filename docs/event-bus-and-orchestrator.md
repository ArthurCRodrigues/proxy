# Event Bus & Orchestrator

The orchestrator is the central runtime loop that connects the event bus, state machine, and all side effects.

## Event bus

The `EventBus` wraps a single `asyncio.Queue[Event]` with `maxsize` (default 256). Any component with a reference can publish events. The orchestrator is the sole consumer.

```python
class EventBus:
    async def publish(event: Event) -> None
    async def next_event() -> Event
    def task_done() -> None
```

## Orchestrator loop

```
while running and state != STOPPED:
    event = await bus.next_event()
    await handle_event(event)
    bus.task_done()
    await asyncio.sleep(0)
```

The `asyncio.sleep(0)` yields control so other coroutines (TTS, STT, wake detection) get CPU time.

## Event handling

`handle_event(event)` does four things in order:

**1. Stale event filtering** — If an assistant event's `turn_id` doesn't match the current context, it's dropped. This prevents responses from cancelled turns from leaking through.

**2. State transition** — Calls `apply_event(ctx, event)`. Invalid transitions are caught and logged at debug level.

**3. Timeout management** — Entering LISTENING arms the timeout. Leaving LISTENING cancels it. `USER_PARTIAL` events re-arm the timeout (resets the inactivity clock during speech).

**4. Side effects** — Based on event type:
- `WAKE` → calls `on_wake()` callback, then publishes `READY`
- `USER_FINAL` → sends text to Copilot via `send_user_turn()`
- `INTERRUPT` → calls `on_interrupt()` callback (cancels Copilot turn, stops TTS, drains queue)

## Listening timeout

When entering LISTENING, an async task sleeps for `listening_timeout_ms` (default 10s) then publishes `LISTENING_TIMEOUT`. Any `USER_PARTIAL` resets the clock. Setting timeout to `0` disables it.
