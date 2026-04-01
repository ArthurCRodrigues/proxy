# TARS v1 Implementation Roadmap

## 1) Project Objective

Build a local, always-on, wake-word-driven voice coding assistant named **TARS** that:

- Listens for wake word **"Tars"**
- Immediately responds with **"Yes?"**
- Starts and binds a **fresh Copilot CLI session** (prewarmed for low latency)
- Accepts spoken coding requests
- Executes coding workflows through Copilot CLI in autonomous mode
- Speaks responses back using natural voice
- Supports instant **barge-in** (user interruption while assistant is speaking)

---

## 2) Locked Scope (v1)

### In Scope

- Wake word detection (local)
- VAD / utterance boundary handling (local)
- Streaming STT via Deepgram
- Copilot CLI bridge with prewarmed session strategy
- Streaming TTS via ElevenLabs
- Event-driven orchestration with explicit state machine
- Hotkey hard-stop
- Crash/timeout recovery for core components
- Minimal local logging and diagnostics

### Out of Scope (v1)

- Cross-session memory and retrieval
- Multi-user profiles / voice authentication
- GUI dashboard
- Advanced policy/guardrail system
- Multi-device synchronization

---

## 3) High-Level Architecture

```text
Microphone
  -> audio_io
  -> wake_vad ------------------------------+
                                            |
                                            v
                                     orchestrator <-> copilot_bridge <-> Copilot CLI process
                                            |
                                            +-> stt_deepgram (streaming WS)
                                            |
                                            +-> tts_elevenlabs (streaming audio)
                                            |
                                            +-> speaker output
```

Design principle: **local control, cloud quality**.

- Local: timing-critical control loop (wake, VAD, barge-in, state)
- Cloud: STT/TTS quality and naturalness

---

## 4) State Machine (Authoritative)

States:

- `IDLE`
- `WAKE_DETECTED`
- `LISTENING`
- `THINKING`
- `SPEAKING`
- `INTERRUPTING`
- `STOPPED`

Main transitions:

1. `IDLE --WAKE--> WAKE_DETECTED`
2. `WAKE_DETECTED --ready--> LISTENING`
3. `LISTENING --USER_FINAL--> THINKING`
4. `THINKING --ASSISTANT_PARTIAL--> SPEAKING`
5. `SPEAKING --ASSISTANT_FINAL--> IDLE`
6. `SPEAKING/THINKING --BARGE_IN--> INTERRUPTING --done--> LISTENING`
7. `* --STOP--> STOPPED`

Invariant: only orchestrator mutates state.

---

## 5) Event Contract (Canonical Bus Schema)

All events should include:

- `event_id` (uuid)
- `ts` (epoch ms)
- `session_id`
- `turn_id` (nullable in idle)
- `type`
- `payload` (typed object)

Event types:

- `WAKE`
- `USER_SPEECH_START`
- `USER_PARTIAL`
- `USER_FINAL`
- `ASSISTANT_PARTIAL`
- `ASSISTANT_FINAL`
- `BARGE_IN`
- `INTERRUPT_ACK`
- `TOOL_START`
- `TOOL_END`
- `SESSION_EXIT`
- `ERROR`
- `STOP`

Queue rules:

- Bounded queue size
- Drop stale partial transcript/token events after state/turn change
- Preserve ordering within same turn

---

## 6) Repository Layout

```text
tars/
  pyproject.toml
  README.md
  .env.example
  tars/
    __init__.py
    main.py
    config.py
    types.py
    orchestrator/
      engine.py
      state_machine.py
      event_bus.py
      timers.py
    audio/
      io.py
      wake_vad.py
      playback.py
    stt/
      base.py
      deepgram_adapter.py
    tts/
      base.py
      elevenlabs_adapter.py
    copilot/
      bridge.py
      session_pool.py
      parser.py
    control/
      hotkeys.py
      commands.py
    observability/
      logger.py
      metrics.py
      traces.py
    tests/
      unit/
      integration/
      e2e/
```

---

## 7) Module-by-Module Build Plan

## Phase 0 - Bootstrap

Deliverables:

- Python project scaffold with dependency management
- `.env.example` with required keys:
  - `DEEPGRAM_API_KEY`
  - `ELEVENLABS_API_KEY`
  - `ELEVENLABS_VOICE_ID`
- Structured logging baseline
- CLI entrypoint: `python -m tars.main`

Validation:

- App starts, loads config, exits cleanly on Ctrl+C

---

## Phase 1 - Event Bus + State Machine Core

Deliverables:

- Async event bus with publish/subscribe
- State reducer with strict transition map
- Turn/session identifiers and lifecycle management
- Unit tests for legal/illegal transitions

Validation:

- Synthetic event replay validates deterministic state transitions

---

## Phase 2 - Audio Input/Output Foundations

Deliverables:

- Microphone capture stream (mono, fixed sample rate)
- Speaker playback stream
- Cached local `"Yes?"` audio asset for zero-network startup
- Playback cancellation primitive (for barge-in)

Validation:

- Audio loopback test
- `"Yes?"` playback < expected local startup threshold

---

## Phase 3 - Wake Word + VAD

Deliverables:

- Wake engine tuned for keyword `"Tars"`
- VAD start/end detection with silence timeout
- Emission of `WAKE`, `USER_SPEECH_START`, end-of-utterance trigger

Validation:

- Wake false-positive/false-negative smoke test
- VAD segmentation works on short and long utterances

---

## Phase 4 - Deepgram Streaming STT Adapter

Deliverables:

- WebSocket streaming client
- Audio chunk push pipeline
- Partial and final transcript callbacks mapped to events
- Reconnect logic with bounded backoff

Validation:

- Live speech produces `USER_PARTIAL` and `USER_FINAL`
- Network interruption recovers without full app restart

---

## Phase 5 - Copilot Bridge + Session Pool

Deliverables:

- Subprocess wrapper around Copilot CLI
- Streaming stdin/stdout handling (non-blocking)
- Contract methods:
  - `prewarm_session()`
  - `activate_session_on_wake()`
  - `send_user_turn(text)`
  - `interrupt_turn()`
  - `hard_stop()`
  - `rollover_session()`
- One-active + one-standby prewarm policy

Validation:

- Fresh prewarmed session becomes active on wake
- Assistant output token stream mapped to assistant events
- Crash of active process triggers standby replacement

---

## Phase 6 - ElevenLabs Streaming TTS Adapter

Deliverables:

- Streaming synthesis client for incremental text chunks
- Chunked audio playback pipeline
- TTS cancel path integrated with barge-in

Validation:

- `ASSISTANT_PARTIAL` leads to audible output quickly
- Barge-in stops TTS audio immediately

---

## Phase 7 - Orchestrator Integration

Deliverables:

- End-to-end turn controller:
  - Wake -> `"Yes?"` -> listen -> transcribe -> Copilot -> speak
- Barge-in path:
  - cancel playback + interrupt Copilot + reopen listening
- Session rollover after conversation end

Validation:

- 10-turn manual scenario with at least:
  - 2 interrupted turns
  - 1 Copilot process restart
  - 1 STT reconnect

---

## Phase 8 - Operational Controls

Deliverables:

- Global hotkeys:
  - Hard stop all components
  - Optional push-to-talk debug mode
- Health monitor/watchdog for component liveness
- Auto-restart for failed adapters/bridge where possible

Validation:

- Forced component failures recover without rebooting machine

---

## Phase 9 - Testing and Stabilization

Test layers:

- Unit:
  - state reducer
  - event routing
  - parser/token handling
- Integration:
  - stt adapter stream lifecycle
  - tts adapter cancellation
  - copilot bridge spawn/interrupt/restart
- E2E:
  - wake-driven full turn
  - barge-in correctness
  - repeated wake sessions

Acceptance criteria:

- Wake word reliably starts workflow
- `"Yes?"` always plays
- Speech in/speech out stable across repeated sessions
- Interrupts are immediate and deterministic
- No manual confirmations required

---

## 8) Performance Strategy

Primary levers:

- Keep wake/VAD local
- Prewarm next Copilot session continuously
- Stream everything (STT in, Copilot tokens, TTS out)
- Use cached `"Yes?"` local audio
- Keep orchestration non-blocking (`asyncio`)

Measurements to capture:

- Wake detect to `"Yes?"` playback start
- End-of-user speech to first assistant token
- First assistant token to first TTS audio
- Barge-in signal to audio halt

---

## 9) Error Handling and Recovery Matrix

- STT disconnect -> reconnect and resume listening state
- TTS failure mid-turn -> emit error, continue text pipeline, allow retry next turn
- Copilot process exit -> emit `SESSION_EXIT`, promote standby, spawn new standby
- Queue overload -> drop stale partials, preserve finals/errors
- Unknown state transition -> log error + fail closed to `IDLE` or `STOPPED`

---

## 10) Configuration and Secrets

Use environment variables only.

Required:

- `DEEPGRAM_API_KEY`
- `ELEVENLABS_API_KEY`
- `ELEVENLABS_VOICE_ID`

Recommended runtime config:

- audio sample rate
- VAD silence threshold
- barge-in sensitivity
- reconnect backoff caps
- logging verbosity

---

## 11) Day-1 Developer Workflow

1. Create venv and install project deps
2. Populate `.env`
3. Run app in verbose mode
4. Validate:
   - wake detection
   - one full turn
   - one interrupted turn
5. Run unit + integration tests

---

## 12) MVP Completion Definition

TARS v1 is complete when:

- Wake word starts a fresh working Copilot-backed voice interaction loop
- You can speak coding requests and hear natural spoken responses
- Barge-in interruption is consistent
- Session prewarm/rollover is reliable
- Core failure paths recover automatically
- System runs repeatedly without operator confirmations

---

## 13) Post-v1 Backlog (Not Implemented in v1)

- Cross-session memory bootstrap
- Context retrieval by project fingerprint
- Voice profile personalization
- Better wake model tuning and noise adaptation
- Optional local fallback STT/TTS

