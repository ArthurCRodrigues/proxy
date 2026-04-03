# State Machine

Proxy's behavior is governed by a deterministic, pure-function state machine. Every state transition is computed by a single function — `apply_event(ctx, event)` — that takes the current context and an event and returns a new context. There are no side effects inside the state machine itself; all side effects are handled by the orchestrator engine after the transition.

## Context

The state machine operates on an `OrchestratorContext` dataclass:

```python
@dataclass
class OrchestratorContext:
    state: AssistantState  # current state (default: IDLE)
    session_id: str | None  # Copilot session scope
    turn_id: str | None     # unique per listening→response cycle
```

`session_id` groups events within a wake→response cycle. `turn_id` is more granular — it identifies a single user utterance and its corresponding assistant response. The orchestrator uses `turn_id` to discard stale assistant events from previous turns.

## States

| State | Meaning |
|---|---|
| `IDLE` | Waiting for wake word. No active session context. |
| `WAKE_DETECTED` | Wake word recognized. Wake handling (sound playback, session promotion) is in progress. |
| `LISTENING` | Microphone audio is being forwarded to Deepgram. Waiting for the user to finish speaking. |
| `THINKING` | User transcript has been sent to Copilot. Waiting for the first response chunk. |
| `SPEAKING` | Copilot is streaming a response. Partial text is being synthesized and played back. |
| `STOPPED` | Terminal state. The system is shutting down. |

## Transitions

```
IDLE ──WAKE──► WAKE_DETECTED ──READY──► LISTENING ──USER_FINAL──► THINKING
  ▲                                        │                         │
  │                              CANCEL / TIMEOUT              ASSISTANT_PARTIAL
  │                                        │                         │
  └────────────────────────────────────────┘                         ▼
  ▲                                                              SPEAKING
  │                                                                  │
  └──────────────────── ASSISTANT_FINAL ─────────────────────────────┘
```

### Per-state rules

**IDLE:**
- `WAKE` → `WAKE_DETECTED`. A new `session_id` is assigned. `turn_id` is cleared.
- All other events raise `InvalidTransitionError` (caught and logged by the engine).

**WAKE_DETECTED:**
- `READY` → `LISTENING`. A new `turn_id` is generated. This event is published by the orchestrator itself after the wake handler completes.

**LISTENING:**
- `USER_FINAL` → `THINKING`. The existing `turn_id` is preserved.
- `CANCEL` → `IDLE`. Both `session_id` and `turn_id` are cleared.
- `LISTENING_TIMEOUT` → `IDLE`. Same as cancel.

**THINKING:**
- `ASSISTANT_PARTIAL` → `SPEAKING`. Context is preserved.
- `ASSISTANT_FINAL` → `IDLE`. Context is cleared. This happens when Copilot returns a short response with no streaming partials.

**SPEAKING:**
- `ASSISTANT_PARTIAL` → `SPEAKING` (no-op). Context is preserved.
- `ASSISTANT_FINAL` → `IDLE`. Context is cleared.

**STOPPED:**
- All events raise `InvalidTransitionError`. This is a terminal state.

### Global transitions

These are handled before per-state logic and apply regardless of current state:

- `STOP` → `STOPPED` from any state. Context is preserved (for debugging).
- `ERROR` → no-op. Returns context unchanged. Errors are logged by the engine but don't affect state.
- `USER_PARTIAL` → no-op. Returns context unchanged. The engine uses this event to reset the listening timeout, but the state machine itself ignores it.

## Design decisions

**Why is the state machine a pure function?** Testability. Every transition can be verified with a simple `assert apply_event(ctx, event).state == expected` without mocking anything. The engine handles all async side effects separately.

**Why does ASSISTANT_FINAL go directly to IDLE?** There is no post-response state. Once Copilot finishes, Proxy is immediately ready for the next wake word. The TTS pipeline drains independently — it doesn't block the state machine.

**Why are session_id and turn_id cleared on return to IDLE?** This prevents stale events from a previous cycle from being processed. The engine's stale-event filter checks `turn_id` before applying assistant events.
