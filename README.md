# TARS (Proxy)

Give your coding agent a real voice in minutes.

TARS is an open-source, voice-first runtime for coding agents. Say the wake word, speak your request, and hear spoken responses with low-latency streaming playback. No local voice-clone stack required.

## Why people use TARS

- Voice in, voice out for coding sessions without switching tools.
- Keeps conversational context by reusing a persistent Copilot session.
- Streams responses while the model is still generating, so replies feel live.
- Built for local wake detection and practical day-to-day coding flow.

## The experience

1. Say the wake word.
2. Ask your coding question out loud.
3. TARS transcribes with Deepgram, sends to Copilot, and speaks back with ElevenLabs.
4. Keep going in the same session with full context continuity.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
python -m proxy.main
```

Then fill in API keys in `.env` and make sure Copilot CLI is installed and authenticated.

## Requirements

- Python 3.11+
- PortAudio (used by `sounddevice`)
- A Vosk model for wake detection
- Copilot CLI
- Deepgram API key
- ElevenLabs API key and voice ID

## How it works

```text
Mic
  -> AudioIO
  -> WakeVadEngine (Vosk + RMS VAD)
  -> Deepgram STT
  -> CopilotBridge (ACP)
  -> TTS chunking
  -> ElevenLabs
  -> PlaybackEngine
  -> Speaker
```

### Runtime flow

- `IDLE`: waits for wake word.
- `WAKE_DETECTED` -> `LISTENING`: promotes a prewarmed Copilot session and starts listening.
- `THINKING`: sends finalized user text to Copilot.
- `SPEAKING`: streams partial assistant text as spoken chunks.
- `IDLE`: returns ready for the next turn.

## What makes TARS feel fast

- Standby session prewarm: ready-to-go session activation on wake.
- Streaming pipeline end to end: STT, model output, and TTS are all incremental.
- Sentence-aware chunking: speech starts early while keeping natural boundaries.

## Built-in protections

- Anti self-listening with `SpeechGate` and `EchoFilter`.
- State-gated STT forwarding so only user-intent windows are transcribed.
- Cancel commands and listening timeout handling in the orchestration loop.

## Copilot integration details

TARS uses Copilot ACP (`copilot --acp --stdio`) with JSON-RPC. It creates and manages sessions, sends prompts through `session/prompt`, and consumes streaming deltas from `session/update`.

## Repository structure

```text
proxy/
  main.py
  config.py
  types.py
  audio/
  stt/
  copilot/
  tts/
  orchestrator/
  observability/
tests/
  unit/
docs/
```

## Configuration

Use `.env.example` as the full reference. The main groups are:

- Credentials: Deepgram and ElevenLabs keys
- Audio I/O: sample rate, channels, device selection
- Wake and VAD: phrase, aliases, thresholds, cooldowns
- STT behavior: endpointing, interim transcripts, reconnect settings
- Turn controls: gate hold, echo filtering, timeout, cancel commands
- Copilot bridge: command, model, instruction path
- TTS partial speech: chunk size and force flush controls

## Wake model setup

Place a Vosk model at `assets/models/vosk-model-small-en-us-0.15`, or set `PROXY_VOSK_MODEL_PATH` to your custom model directory.

## Testing

```bash
pytest -q
```

## Roadmap and docs

- Lifecycle walkthrough: `docs/lifecycle.md`
- State machine details: `docs/state-machine.md`
- Copilot ACP integration: `docs/copilot-integration.md`
- Launch direction: `docs/project-launch-roadmap.md`

## Contributing

Issues and pull requests are welcome. If you are building voice support for another coding agent, this codebase is intentionally structured so the agent bridge layer can be extended without rewriting the wake, STT, TTS, and orchestration core.
