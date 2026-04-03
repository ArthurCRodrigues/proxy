# TARS

TARS is a voice-first coding runtime built around Copilot CLI. It listens for a wake phrase, captures speech, sends prompts to Copilot, and speaks responses back with low-latency streaming.

## Architecture at a glance

```text
Mic (sounddevice) -> AudioIO -> WakeVadEngine (Vosk + RMS VAD) -> EventBus
                                                     |
                                                     +-> Deepgram STT (partial/final)

EventBus <-> Orchestrator (state + turn/session routing) <-> CopilotBridge
                                                           (ACP warm process or subprocess JSONL)

Copilot events -> TTS chunking -> ElevenLabs adapter -> PlaybackEngine -> Speaker
```

Core design:
- local control loop for wake, VAD, state, cancellation, anti-echo gating
- cloud STT/TTS for quality
- persistent Copilot context with session pool and ACP default

## Runtime lifecycle

1. Boot initializes config, audio I/O, STT, TTS, event bus, orchestrator, and Copilot bridge.
2. A standby Copilot session is prewarmed at startup.
3. Wake phrase detection (`WAKE`) transitions to `WAKE_DETECTED`, then `READY` to `LISTENING`.
4. User speech final (`USER_FINAL`) moves to `THINKING` and is sent to Copilot.
5. Copilot deltas/finals become `ASSISTANT_PARTIAL`/`ASSISTANT_FINAL`, which feed TTS.
6. Final response returns the state to `IDLE`.

## Authoritative state machine

States:
- `IDLE`
- `WAKE_DETECTED`
- `LISTENING`
- `THINKING`
- `SPEAKING`
- `INTERRUPTING`
- `STOPPED`

Key transitions:
- `IDLE + WAKE -> WAKE_DETECTED`
- `WAKE_DETECTED + READY -> LISTENING`
- `LISTENING + USER_FINAL -> THINKING`
- `THINKING + ASSISTANT_PARTIAL -> SPEAKING`
- `THINKING|SPEAKING + BARGE_IN -> INTERRUPTING`
- `INTERRUPTING + INTERRUPT_ACK -> LISTENING`
- `THINKING|SPEAKING + ASSISTANT_FINAL -> IDLE`
- `LISTENING + CANCEL|LISTENING_TIMEOUT -> IDLE`
- `* + STOP -> STOPPED`

## Event model

Canonical event types are defined in `tars/types.py`:

- User/audio control: `WAKE`, `USER_SPEECH_START`, `USER_SPEECH_END`, `USER_PARTIAL`, `USER_FINAL`, `BARGE_IN`, `CANCEL`, `LISTENING_TIMEOUT`
- Assistant/Copilot: `ASSISTANT_PARTIAL`, `ASSISTANT_FINAL`, `TOOL_START`, `TOOL_END`, `SESSION_EXIT`
- System: `READY`, `ERROR`, `INTERRUPT_ACK`, `STOP`

Each event has `event_id`, `ts`, and optional `session_id`/`turn_id`.

## Copilot integration

`CopilotBridge` supports two modes:

1. **ACP mode (default)**: starts `copilot --acp --stdio`, initializes JSON-RPC, opens sessions via `session/new`, sends prompts via `session/prompt`, and streams partials from `session/update`.
2. **Subprocess JSONL mode**: runs `copilot -p ... --output-format json` and parses JSON lines.

Session behavior:
- standby + active session pool (`SessionPool`)
- wake activation promotes standby to active
- rollover prewarms next standby session
- `start new session` voice command resets active Copilot context

Bootstrap behavior:
- if enabled, prepends `copilot-instructions.md` content to first prompt in a session

## Speech pipeline

TTS is event-driven:
- partial deltas are appended into a text buffer
- chunking emits speakable segments at punctuation/newline boundaries with configurable thresholds
- finals flush remaining buffered text
- when partial speech is enabled, final dedupe avoids replaying already-spoken content

Chunking controls:
- `TARS_TTS_SPEAK_PARTIALS`
- `TARS_TTS_PARTIAL_MIN_CHARS`
- `TARS_TTS_PARTIAL_FORCE_FLUSH_CHARS` (`0` disables forced boundaryless flush)

ElevenLabs adapter:
- default output `pcm_22050`
- fallback output formats if primary format is denied
- resilient synthesis path so one failed chunk does not collapse runtime loop

## Anti self-listening protections

TARS uses two layers to reduce transcribing its own voice:

1. `SpeechGate`: blocks STT acceptance for a hold window after TTS playback starts.
2. `EchoFilter`: keeps recent assistant text and rejects STT transcripts with strong similarity.

Additionally, STT forwarding is gated by orchestrator state (`LISTENING` only).

## Logging and observability

`configure_logger()` sets global formatting and suppresses noisy third-party internals:
- `websockets`, `websockets.client`, `asyncio`, `httpcore`, `httpx` => warning-level

Useful runtime logs:
- state transitions (`tars.orchestrator`)
- wake events (`tars.wake_vad`)
- Copilot prompt/session lifecycle (`tars.copilot.bridge`)
- STT partial/final and drops (`tars.main`, `tars.stt.deepgram`)
- TTS synthesis/playback issues (`tars.tts.elevenlabs`)

## Repository structure

```text
tars/
  main.py                    # Wiring and runtime orchestration
  config.py                  # Environment-backed settings
  types.py                   # Event/state enums and event dataclass
  audio/
    io.py                    # Mic capture stream wrapper
    wake_vad.py              # Wake word + RMS VAD loop
    playback.py              # PCM output playback
    assets.py                # WAV loading and wake sound selection
  stt/
    deepgram_adapter.py      # Deepgram websocket streaming adapter
    filtering.py             # Speech gate + echo filter
  copilot/
    bridge.py                # ACP + subprocess Copilot transport
    parser.py                # JSONL event parser
    session_pool.py          # Standby/active session management
  tts/
    elevenlabs_adapter.py    # ElevenLabs synthesis adapter
    chunking.py              # Partial/final text segmentation and merge rules
  orchestrator/
    event_bus.py             # Async queue bus
    state_machine.py         # Deterministic reducer
    engine.py                # Event loop and side effects
  observability/
    logger.py                # Logger configuration
tests/
  unit/                      # State, bridge, chunking, adapters
```

## Requirements

- Python 3.11+
- Local audio input/output support (PortAudio via `sounddevice`)
- Vosk model files for wake detection
- Copilot CLI installed and authenticated
- API keys for:
  - Deepgram
  - ElevenLabs

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
python -m tars.main
```

## Environment configuration

Use `.env.example` as the source of truth. Main groups:

- API credentials: `DEEPGRAM_API_KEY`, `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID`
- Runtime: `TARS_LOG_LEVEL`, queue sizing
- Audio I/O: sample rate/channels/chunk/device
- Wake/VAD: wake phrase/aliases, Vosk path, RMS thresholds, cooldowns, debug flags
- Deepgram STT: model/language/endpointing/utterance, keyterms, reconnect
- Speech turn controls: STT gate/de-echo/listening timeout/cancel commands
- Copilot bridge: command/model/allow-all/bootstrap/ACP toggle
- Assistant speech output: partial controls and chunk thresholds

## Wake model setup

Place a Vosk model at:

`assets/models/vosk-model-small-en-us-0.15`

Or set a custom path with `TARS_VOSK_MODEL_PATH`.

## Benchmarking Copilot latency

Run:

```bash
python benchmark_copilot_latency.py --runs 5
```

Measures:
- classic `copilot -p` end-to-end process latency
- warm ACP prompt latency (timer starts at `session/prompt` send, not ACP startup)

Useful flags:
- `--prompt "..."`
- `--model ...`
- `--fresh-acp-session-per-run`
- `--json`

## Testing

```bash
pytest -q
```
