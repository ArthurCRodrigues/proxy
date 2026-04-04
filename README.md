# Proxy

Proxy is an event-driven voice assistant that sits between a user and GitHub Copilot CLI. It listens for a wake word through a local speech model, transcribes the user's voice via Deepgram, sends the transcription to a persistent Copilot ACP session, and speaks the response back through ElevenLabs TTS — all with streaming, low-latency playback.

## How it works

```
Mic ─► AudioIO ─► WakeVadEngine (Vosk wake word + RMS VAD)
                       │
                       ├─ wake detected ──► EventBus ──► Orchestrator
                       │                                     │
                       └─ audio chunks ──► Deepgram STT      │
                                               │             │
                                          USER_FINAL ────────┘
                                                              │
                                                        CopilotBridge (ACP)
                                                              │
                                                     ASSISTANT_PARTIAL / FINAL
                                                              │
                                              Realtime TTS text queue ─► ElevenLabs WS
                                                                        │
                                                                   PlaybackEngine ─► Speaker
```

## Lifecycle

1. On startup, Proxy launches a background Copilot ACP process and prewarms a standby session. The session is immediately bootstrapped with system instructions so subsequent prompts carry no bootstrap overhead.

2. The system enters `IDLE` and the wake engine continuously listens for the configured wake phrase using a local Vosk model.

3. When the wake word is detected, Proxy plays a random acknowledgment sound from a local assets directory, promotes the standby Copilot session to active, and begins prewarming the next standby session. The state machine transitions through `WAKE_DETECTED` → `LISTENING`.

4. While in `LISTENING`, audio is forwarded to Deepgram for streaming transcription. A local RMS-based VAD detects end-of-speech silence and triggers Deepgram to finalize the transcript. If the user says a cancel phrase (e.g. "never mind"), the system returns to `IDLE`. A configurable inactivity timeout does the same if the user stays silent.

5. On a finalized transcript (`USER_FINAL`), the state moves to `THINKING` and the text is sent to the active Copilot session. No new session is created — the existing one preserves full conversational context.

6. As Copilot streams back partial responses, they are pushed in-order to a single ElevenLabs WebSocket stream. Audio chunks are played as they arrive, so the user hears speech while Copilot is still generating. The state is `SPEAKING` during this phase.

7. When Copilot emits its final response, Proxy finalizes the active TTS stream and the state returns to `IDLE`. The same Copilot session remains active for conversational continuity unless the user explicitly says "start new session."

## State machine

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

States: `IDLE`, `WAKE_DETECTED`, `LISTENING`, `THINKING`, `SPEAKING`, `STOPPED`

Global transitions:
- `STOP` → `STOPPED` (from any state)
- `ERROR`, `USER_PARTIAL` → no-op (from any state)

## Event types

| Event | Published by | Purpose |
|---|---|---|
| `WAKE` | WakeVadEngine | Wake phrase detected by Vosk |
| `READY` | Orchestrator | Wake handling complete, begin listening |
| `USER_PARTIAL` | main (STT callback) | Interim transcript; resets listening timeout |
| `USER_FINAL` | main (STT callback) | Finalized transcript; triggers Copilot prompt |
| `CANCEL` | main (STT callback) | Cancel phrase detected; returns to IDLE |
| `LISTENING_TIMEOUT` | Orchestrator | No speech activity within timeout window |
| `ASSISTANT_PARTIAL` | CopilotBridge | Streaming text chunk from Copilot |
| `ASSISTANT_FINAL` | CopilotBridge | Complete response from Copilot |
| `ERROR` | CopilotBridge | ACP prompt failure (logged, no state change) |
| `STOP` | main (shutdown) | Terminates the orchestrator loop |

## Anti self-listening

Two layers prevent Proxy from transcribing its own voice:

- `SpeechGate` — blocks STT acceptance for a configurable hold window after TTS playback starts.
- `EchoFilter` — keeps recent assistant text and rejects STT transcripts with high similarity (SequenceMatcher ratio).

STT forwarding is also gated by orchestrator state — audio only reaches Deepgram while in `LISTENING`.

## Copilot integration

`CopilotBridge` communicates exclusively through ACP (Agent Control Protocol): it starts `copilot --acp --stdio`, initializes a JSON-RPC connection, creates sessions via `session/new`, and sends prompts via `session/prompt`. Streaming deltas arrive through `session/update` notifications.

`SessionPool` manages a standby + active session pair. On wake, the standby is promoted to active and a new standby is prewarmed in the background. Bootstrap instructions are sent once per session at creation time.

## TTS pipeline

Copilot partial deltas are fed into a single ordered text queue and pushed incrementally to ElevenLabs over WebSocket. The adapter receives audio chunks in realtime and streams them to playback without waiting for full-response synthesis. On cancellation, active playback and stream are interrupted immediately.

Configuration:
- `PROXY_TTS_TEXT_QUEUE_MAXSIZE` — max buffered outbound text commands
- `PROXY_TTS_AUDIO_QUEUE_MAXSIZE` — max buffered inbound audio chunks

## Repository structure

```
proxy/
  main.py                    # Wiring, runtime orchestration, STT/TTS callbacks
  config.py                  # Environment-backed settings (PROXY_* env vars)
  types.py                   # EventType, AssistantState enums, Event dataclass
  audio/
    io.py                    # Mic capture stream (sounddevice)
    wake_vad.py              # Vosk wake word detection + RMS VAD
    playback.py              # PCM audio output
    assets.py                # WAV loading, wake sound selection
  stt/
    deepgram_adapter.py      # Deepgram websocket streaming STT
    filtering.py             # SpeechGate + EchoFilter
  copilot/
    bridge.py                # ACP JSON-RPC transport, prompt execution, bootstrap
    session_pool.py          # Standby/active session management
  tts/
    elevenlabs_adapter.py    # ElevenLabs realtime websocket adapter
  orchestrator/
    event_bus.py             # Async queue event bus
    state_machine.py         # Deterministic state reducer
    engine.py                # Event loop, side effects, listening timeout
  observability/
    logger.py                # Logger configuration
tests/
  unit/                      # State machine, bridge, chunking, adapters, VAD
```

## Requirements

- Python 3.11+
- PortAudio (via `sounddevice`)
- Vosk model for wake detection
- Copilot CLI installed and authenticated
- API keys: Deepgram, ElevenLabs

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env       # fill in API keys
python -m proxy.main
```

## Wake model setup

Place a Vosk model at `assets/models/vosk-model-small-en-us-0.15`, or set `PROXY_VOSK_MODEL_PATH` to a custom location.

## Environment configuration

See `.env.example` for all available settings. Key groups:

- API credentials: `DEEPGRAM_API_KEY`, `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID`
- Runtime: `PROXY_LOG_LEVEL`, `PROXY_QUEUE_MAXSIZE`
- Audio: sample rate, channels, chunk size, input device
- Wake/VAD: wake phrase and aliases, Vosk path, RMS thresholds, cooldowns
- Deepgram: model, language, endpointing, utterance end, keyterms
- Speech turn: STT gate, echo filter, listening timeout, cancel commands
- Copilot: command, model, bootstrap instructions path
- TTS: realtime stream queue sizing and voice parameters

## Testing

```bash
pytest -q
```
