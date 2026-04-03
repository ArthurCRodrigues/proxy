# Event Bus & Orchestrator

The orchestrator is the central runtime loop that connects the event bus, state machine, and all side effects. It consumes events, applies state transitions, and triggers the appropriate actions.

## Event bus

The `EventBus` is a thin wrapper around a single `asyncio.Queue[Event]`:

```python
class EventBus:
    async def publish(event: Event) -> None   # put event on queue (blocks if full)
    async def next_event() -> Event           # get next event (blocks until available)
    def task_done() -> None                   # signal event processing complete
```

There is no topic filtering or fan-out. Every event goes through one queue. The `maxsize` (default 256, configurable via `PROXY_QUEUE_MAXSIZE`) provides backpressure — if the queue fills up, publishers block until the orchestrator drains it.

Any component with a reference to the bus can publish events: `WakeVadEngine` publishes `WAKE`, `main.py` callbacks publish `USER_PARTIAL`/`USER_FINAL`/`CANCEL`, `CopilotBridge` publishes `ASSISTANT_PARTIAL`/`ASSISTANT_FINAL`/`ERROR`, and the orchestrator itself publishes `READY` and `LISTENING_TIMEOUT`.

## Event anatomy

Every event is a frozen dataclass:

```python
@dataclass(frozen=True)
class Event:
    type: EventType                # the event kind (enum)
    session_id: str | None         # scoping to a wake cycle
    turn_id: str | None            # scoping to a single utterance/response
    payload: dict[str, Any]        # event-specific data (e.g. {"text": "..."})
    event_id: str                  # auto-generated UUID
    ts: int                        # epoch milliseconds timestamp
```

`session_id` and `turn_id` are optional. Most events published by external components (wake engine, STT callbacks) don't set them — the orchestrator tracks these in its own context. The bridge sets them on assistant events so the engine can filter stale responses.

## Orchestrator loop

The `Orchestrator.run()` method is the main loop:

```
while running and state != STOPPED:
    event = await bus.next_event()
    await handle_event(event)
    bus.task_done()
    await asyncio.sleep(0)  # yield to other tasks
```

The `asyncio.sleep(0)` at the end of each iteration is critical — it yields control to the event loop so that other coroutines (TTS playback, STT streaming, wake detection) get CPU time.

## Event handling

`handle_event(event)` does four things in order:

### 1. Stale event filtering

If an event has a `turn_id` that doesn't match the orchestrator's current `turn_id`, and the event is `ASSISTANT_PARTIAL` or `ASSISTANT_FINAL`, it is silently dropped. This prevents responses from a previous turn (e.g. after a session reset) from corrupting the current interaction.

### 2. State transition

The event is passed to `apply_event(ctx, event)`. If the state machine raises `InvalidTransitionError`, the event is logged at debug level and discarded. This is the normal path for events that arrive in unexpected states (e.g. a `USER_FINAL` arriving while in `IDLE`).

### 3. Timeout management

If the state changed:
- Entering `LISTENING` → arms the listening timeout.
- Leaving `LISTENING` → cancels the listening timeout.

If the state did NOT change but we're in `LISTENING` and got a `USER_PARTIAL`:
- Re-arms the listening timeout. This is how speech activity prevents the inactivity timeout from firing during a long utterance.

### 4. Side effects

After the state transition, the orchestrator executes side effects based on the event type:

**On `WAKE`:**
1. Calls the `on_wake` callback (provided by `main.py`), which: promotes the standby session, starts background bootstrap, plays the wake sound, and prewarms the next standby.
2. Publishes a `READY` event to advance the state machine from `WAKE_DETECTED` → `LISTENING`.

**On `USER_FINAL`:**
- Extracts the `text` from the event payload and calls `copilot_bridge.send_user_turn(text, turn_id=...)`.

No other events trigger side effects in the orchestrator.

## Listening timeout

The listening timeout prevents the system from staying in `LISTENING` indefinitely if the user doesn't speak.

When the state enters `LISTENING`, the orchestrator creates an async task that sleeps for `listening_timeout_ms` (default 10 seconds) and then publishes a `LISTENING_TIMEOUT` event. If any `USER_PARTIAL` event arrives while in `LISTENING`, the timeout is cancelled and re-armed — the clock resets.

If the timeout fires, the state machine transitions `LISTENING` → `IDLE`, and Proxy goes back to waiting for the wake word.

The timeout is configurable via `PROXY_LISTENING_TIMEOUT_MS`. Setting it to `0` disables the timeout entirely.
