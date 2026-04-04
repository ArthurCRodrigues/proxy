# Proxy Refactoring Plan

Date: 2026-04-03

## Goal

Strip the codebase to only what the current design requires. Remove legacy code paths, dead modules, and unused abstractions that accumulated during rapid prototyping.

---

## 1. Dead Modules — Full Removal

These modules are defined but never imported or used anywhere in the runtime or tests.

| Module | Reason |
|---|---|
| `proxy/control/hotkeys.py` | Placeholder stub (`HotkeyController`) — no-op methods, never imported |
| `proxy/control/commands.py` | Single-member enum (`ControlCommand.STOP`) — never imported |
| `proxy/control/` (entire package) | Both files are dead; remove the directory |
| `proxy/observability/metrics.py` | `InMemoryMetrics` class — never imported anywhere |
| `proxy/observability/traces.py` | `TracePoint` / `now_trace` — never imported anywhere |
| `proxy/orchestrator/timers.py` | `Stopwatch` class — never imported anywhere |

---

## 2. Dead Functions & Code

| Location | Symbol | Reason |
|---|---|---|
| `proxy/audio/assets.py` | `load_yes_audio()` | Never called. `load_random_wake_audio()` is used instead. The `yes_asset_path` config field and `yes.wav` references exist only to feed the fallback path into `load_random_wake_audio` via `choose_wake_sound`. `load_yes_audio` itself is orphaned. |
| `proxy/copilot/parser.py` | `extract_text_line()` | Never called outside its own file. Dead helper. |
| `proxy/copilot/bridge.py` | `on_session_exit` callback parameter | The callback in `main.py` (`_on_copilot_session_exit`) is a no-op (`return`). The parameter, its storage, and all call sites can be removed. |

---

## 3. Subprocess JSONL Mode — Full Removal

The project description states ACP is the only Copilot integration mode. The subprocess JSONL path is legacy.

Files/code to remove:

| Location | What to remove |
|---|---|
| `proxy/copilot/bridge.py` | `_run_prompt_subprocess()` method |
| `proxy/copilot/bridge.py` | `_run_bootstrap_prompt_subprocess()` method |
| `proxy/copilot/bridge.py` | All `if self._use_acp: ... else:` branching — collapse to ACP-only |
| `proxy/copilot/bridge.py` | `use_acp` constructor parameter and `self._use_acp` field |
| `proxy/copilot/parser.py` | Entire file — `parse_jsonl_event` and `ParsedCopilotEvent` are only used by the subprocess path |
| `proxy/config.py` | `copilot_use_acp` setting and its `TARS_COPILOT_USE_ACP` env var |
| `proxy/main.py` | `use_acp=settings.copilot_use_acp` argument in `CopilotBridge(...)` |
| `tests/unit/test_copilot_parser.py` | Entire test file — tests the removed parser |

---

## 4. Barge-In / Interruption System — Evaluate for Removal

The `BARGE_IN` event, `INTERRUPTING` state, and `INTERRUPT_ACK` flow are wired into the state machine and bridge but are **never triggered** by any runtime code. No component publishes a `BARGE_IN` event. This is a designed-but-unactivated feature.

**Recommendation:** Remove entirely. It can be re-implemented when actually needed.

| Location | What to remove |
|---|---|
| `proxy/types.py` | `BARGE_IN`, `INTERRUPT_ACK` from `EventType`; `INTERRUPTING` from `AssistantState` |
| `proxy/orchestrator/state_machine.py` | All `BARGE_IN` / `INTERRUPTING` / `INTERRUPT_ACK` transition branches |
| `proxy/orchestrator/engine.py` | `BARGE_IN` side-effect handler |
| `proxy/copilot/bridge.py` | `interrupt_turn()` method (only called from barge-in path and `reset_session` — keep the cancel logic in `reset_session` inline if needed) |

---

## 5. Event Bus Audit — Published-but-Useless Events

Full trace of every event type, who publishes it, and what (if anything) consumes it meaningfully:

### `USER_SPEECH_START` / `USER_SPEECH_END` — Remove from bus

- Published by: `wake_vad.py` (VAD RMS tracker)
- State machine: explicit no-op (returns `ctx` unchanged)
- Engine: refreshes the listening timeout — **but this is redundant** because `USER_PARTIAL` events from Deepgram arrive continuously during speech and already refresh the same timeout. Partials are a superset of VAD triggers for timeout purposes.
- The critical side-effect of VAD end-of-speech (`stt.end_utterance()` → Deepgram Finalize) happens **directly in `wake_vad.py`**, not through the event bus. The bus event is just a notification that nothing acts on.
- **Recommendation:** Stop publishing these events. Remove from `EventType`. The `end_utterance()` call stays in `wake_vad.py` where it already lives.

### `USER_PARTIAL` — Keep, but only for timeout refresh

- Published by: `main.py` `_on_partial` callback
- State machine: explicit no-op (returns `ctx` unchanged)
- Engine: refreshes the listening timeout — **this is the only consumer and it's a legitimate use**. Without it, a user speaking a long sentence could hit the 10s inactivity timeout.
- No state transition, no side-effect beyond timeout reset.
- **Recommendation:** Keep. It's the sole mechanism preventing timeout during active speech. However, consider whether this could be simplified to a direct timer reset instead of a full event bus round-trip (future optimization, not blocking).

### `TOOL_START` / `TOOL_END` — Remove

- Defined in `EventType`, handled as no-ops in state machine, never published by any component. Pure dead code.

### `SESSION_EXIT` — Remove

- Published by bridge after prompt completion. State machine: explicit no-op. The `on_session_exit` callback in `main.py` is a literal `return`. No component uses this for anything.

### `ERROR` — Keep, fix handling

- Published by bridge on ACP exceptions. The state machine has no explicit handler — it falls through to `InvalidTransitionError` which the engine catches and logs as "Ignoring invalid transition." This works but is accidental.
- **Recommendation:** Keep the event type. Add an explicit no-op handler in the state machine so it doesn't rely on exception-based flow for a normal operational event.

---

## 6. Naming Cleanup — TARS → Proxy

The project was renamed from TARS to Proxy but env vars and log messages still reference the old name.

| What | Action |
|---|---|
| All `TARS_*` env var names in `config.py` | Rename to `PROXY_*` |
| `main.py` log messages | `"Starting TARS bootstrap"` → `"Starting Proxy bootstrap"`, `"TARS listening..."` → `"Proxy listening..."` |
| `main.py` argparse description | `"TARS voice assistant"` → `"Proxy voice assistant"` |
| `proxy/__init__.py` | `"TARS voice assistant package."` → `"Proxy voice assistant package."` |
| `proxy/audio/__init__.py` | `"Audio components for TARS."` → `"Audio components for Proxy."` |
| `.env.example` (if exists) | Update all `TARS_*` references |

---

## 7. STT Base Class — Evaluate Abstraction Value

`proxy/stt/base.py` defines `STTAdapter` ABC. There is exactly one implementation (`DeepgramSTTAdapter`). The base class is never used for type hints in `main.py` — the concrete class is imported directly.

**Recommendation:** Remove `base.py`. If a second STT provider is added later, the interface can be extracted then. Same applies to `proxy/tts/base.py` (one implementation: `ElevenLabsTTSAdapter`).

---

## 8. Summary of Deletions

### Files to delete entirely:
- `proxy/control/hotkeys.py`
- `proxy/control/commands.py`
- `proxy/control/__init__.py` (if exists)
- `proxy/observability/metrics.py`
- `proxy/observability/traces.py`
- `proxy/orchestrator/timers.py`
- `proxy/copilot/parser.py`
- `proxy/stt/base.py`
- `proxy/tts/base.py`
- `tests/unit/test_copilot_parser.py`

### Files to modify:
- `proxy/copilot/bridge.py` — remove subprocess mode, `use_acp` toggle, `on_session_exit` callback, collapse to ACP-only
- `proxy/orchestrator/state_machine.py` — remove BARGE_IN/INTERRUPTING/INTERRUPT_ACK, TOOL_START/TOOL_END, SESSION_EXIT, USER_SPEECH_START/END; add explicit ERROR no-op
- `proxy/orchestrator/engine.py` — remove barge-in handler, remove USER_SPEECH_START/END from timeout refresh (USER_PARTIAL alone is sufficient)
- `proxy/types.py` — remove: `BARGE_IN`, `INTERRUPT_ACK`, `USER_SPEECH_START`, `USER_SPEECH_END`, `TOOL_START`, `TOOL_END`, `SESSION_EXIT` from `EventType`; remove `INTERRUPTING` from `AssistantState`
- `proxy/audio/wake_vad.py` — stop publishing `USER_SPEECH_START`/`USER_SPEECH_END` events (keep the `end_utterance()` call which is the actual functional part)
- `proxy/config.py` — remove `copilot_use_acp`, rename `TARS_*` → `PROXY_*`
- `proxy/main.py` — remove dead callback, update naming, remove `use_acp` arg
- `proxy/audio/assets.py` — remove `load_yes_audio()`
- `proxy/tts/elevenlabs_adapter.py` — remove `TTSAdapter` base class inheritance (just a standalone class)
- `proxy/stt/deepgram_adapter.py` — remove `STTAdapter` base class inheritance

---

## 9. Execution Order

1. Delete dead modules (§1) — zero risk, nothing depends on them
2. Remove subprocess JSONL mode (§3) — isolated to bridge + parser
3. Remove barge-in system (§4) — touches state machine, engine, bridge, types
4. Clean up unused events/callbacks (§5, §2)
5. Remove base class abstractions (§7)
6. Rename TARS → Proxy (§6) — cosmetic, do last to minimize merge conflicts
7. Run `pytest -q` after each step to verify nothing breaks
