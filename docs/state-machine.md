# State Machine

Proxy's behavior is governed by a deterministic, pure-function state machine. Every state transition is computed by `apply_event(ctx, event)` — no side effects inside the state machine itself.

## Context

```python
@dataclass
class OrchestratorContext:
    state: AssistantState  # current state (default: IDLE)
    session_id: str | None  # Copilot session scope
    turn_id: str | None     # unique per listening→response cycle
```

`turn_id` is used by the orchestrator to discard stale assistant events from previous turns.

## States

| State | Meaning |
|---|---|
| `IDLE` | Waiting for wake word. No active session context. |
| `WAKE_DETECTED` | Wake word recognized. Wake handling (sound playback, session activation) is in progress. |
| `LISTENING` | Audio is being forwarded to Deepgram. Waiting for the user to finish speaking. |
| `THINKING` | User transcript sent to Copilot. Waiting for the first response chunk. |
| `SPEAKING` | Copilot is streaming a response. Text is being synthesized and played back. |
| `STOPPED` | Terminal state. System is shutting down. |

## Transitions

| From | Event | To | Notes |
|---|---|---|---|
| `IDLE` | `WAKE` | `WAKE_DETECTED` | `turn_id` cleared |
| `WAKE_DETECTED` | `READY` | `LISTENING` | New `turn_id` assigned |
| `LISTENING` | `USER_FINAL` | `THINKING` | |
| `LISTENING` | `CANCEL` / `LISTENING_TIMEOUT` | `IDLE` | Context cleared |
| `THINKING` | `ASSISTANT_PARTIAL` | `SPEAKING` | |
| `THINKING` | `ASSISTANT_FINAL` | `IDLE` | Short response, no partials |
| `THINKING` | `INTERRUPT` | `LISTENING` | New `turn_id`, session preserved |
| `SPEAKING` | `ASSISTANT_PARTIAL` | `SPEAKING` | No-op |
| `SPEAKING` | `ASSISTANT_FINAL` | `IDLE` | Context cleared |
| `SPEAKING` | `INTERRUPT` | `LISTENING` | New `turn_id`, session preserved |
| Any | `STOP` | `STOPPED` | |
| Any | `ERROR` / `USER_PARTIAL` | (unchanged) | Global no-ops |

## Event types

| Event | Published by | Purpose |
|---|---|---|
| `WAKE` | WakeVadEngine | Wake phrase detected by Vosk |
| `READY` | Orchestrator | Wake handling complete, begin listening |
| `USER_PARTIAL` | main (STT callback) | Interim transcript; resets listening timeout |
| `USER_FINAL` | main (STT callback) | Finalized transcript; triggers Copilot prompt |
| `CANCEL` | main (STT callback) | Cancel phrase detected; returns to IDLE |
| `INTERRUPT` | WakeVadEngine | Stopword detected during THINKING/SPEAKING |
| `LISTENING_TIMEOUT` | Orchestrator | No speech activity within timeout window |
| `ASSISTANT_PARTIAL` | CopilotBridge | Streaming text chunk from Copilot |
| `ASSISTANT_FINAL` | CopilotBridge | Complete response from Copilot |
| `ERROR` | CopilotBridge | ACP prompt failure (logged, no state change) |
| `STOP` | main (shutdown) | Terminates the orchestrator loop |
