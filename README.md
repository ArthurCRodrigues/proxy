# TARS

TARS is a Python-based voice orchestrator for wake-word-triggered Copilot CLI sessions.

## Current status

This repository currently implements:

- Project scaffold and configuration loading
- Canonical event definitions
- Async event bus
- Deterministic state machine
- Orchestrator core loop with session/turn tracking
- Audio foundation:
  - local WAV asset loading (`assets/yes.wav`)
  - cancellable PCM playback pipeline
  - microphone capture abstraction with chunk queue
- Phase 3 base:
  - local wake-word detection via Vosk
  - RMS-based VAD start/end events
  - wake callback that plays random wake audio
- Phase 4 base:
  - Deepgram streaming STT adapter (partial/final transcripts)
  - utterance finalization trigger on VAD end
  - reconnect logic with bounded backoff
- Phase 5 base:
  - Copilot bridge for prompt execution in JSON output mode
  - assistant token/final event parsing (`ASSISTANT_PARTIAL` / `ASSISTANT_FINAL`)
  - standby session pool activation/rollover hooks
- Unit tests for state transitions and event dispatch

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
python -m tars.main
```

Running `python -m tars.main` starts microphone listening with local wake-word detection.

## Copilot latency benchmark (classic vs ACP warm process)

Run:

```bash
python benchmark_copilot_latency.py --runs 5
```

What it measures:

- **Classic:** starts timer at command launch and stops when `copilot -p ...` exits.
- **ACP warm:** starts Copilot ACP once (not timed), then starts timer exactly when `session/prompt` is sent and stops on the matching `session/prompt` response.

Useful flags:

- `--prompt "your prompt here"`
- `--model <model>`
- `--fresh-acp-session-per-run` (new ACP session each run, same warm ACP process)
- `--json` (machine-readable output)

If `assets/wake/*.wav` exists, TARS randomly picks one wake sound per activation.
If none exist, it falls back to `assets/yes.wav`.

## Vosk model setup (required for wake detection)

Download a Vosk English model and extract it to:

`assets/models/vosk-model-small-en-us-0.15`

You can also set a custom path via `TARS_VOSK_MODEL_PATH`.

## Wake troubleshooting

If wake is not triggering:

- Set microphone explicitly with `TARS_AUDIO_INPUT_DEVICE` (index or device name).
- Add phonetic aliases with `TARS_WAKE_ALIASES` (default: `tars,stars,tarz`).
- Enable transcript debug with `TARS_WAKE_DEBUG_TRANSCRIPTS=1` and `TARS_LOG_LEVEL=DEBUG`.
- Keep RMS logging off by default (`TARS_WAKE_DEBUG_RMS=0`) to avoid terminal noise.
- Wake retrigger cooldown is configurable (`TARS_WAKE_RETRIGGER_COOLDOWN_MS`).

## Deepgram STT notes

Deepgram requires `DEEPGRAM_API_KEY` in `.env`.
The adapter emits partial/final transcripts into event bus as `USER_PARTIAL`/`USER_FINAL`.

For long pauses (for example, ~3s between phrases), tune:

- `TARS_DEEPGRAM_ENDPOINTING_ENABLED=1` and `TARS_DEEPGRAM_ENDPOINTING_MS=3000-3500`, or disable endpointing with `TARS_DEEPGRAM_ENDPOINTING_ENABLED=0`
- `TARS_DEEPGRAM_UTTERANCE_END_MS=3500`
- `TARS_DEEPGRAM_PUNCTUATE=1`
- `TARS_DEEPGRAM_SMART_FORMAT=1`

For code/repo domain biasing on `nova-3`, add `TARS_DEEPGRAM_KEYTERMS` as a comma-separated list.
Recommended starter list for this setup:

`prisma-infrastructure,api-grader-prisma,app-grader-prisma,autograder,prisma backend,prisma frontend,pull request,draft PR,GitHub issue`

To reduce self-transcription (assistant audio captured by mic), TARS includes:

- STT gate (`TARS_STT_GATE_ENABLED`, `TARS_STT_GATE_HOLD_MS`)
- de-echo filter (`TARS_STT_DEECHO_ENABLED`, `TARS_STT_DEECHO_SIMILARITY_THRESHOLD`)
- state-based STT upstream gating: Deepgram audio is only forwarded while state is `LISTENING`

## Copilot bridge notes

Copilot execution is launched via:

- `TARS_COPILOT_COMMAND` (default `copilot`)
- `TARS_COPILOT_MODEL` (optional)
- `TARS_COPILOT_ALLOW_ALL` (default enabled)
- `TARS_COPILOT_ENABLE_FINAL_CONTRACT` (default enabled)
- `TARS_COPILOT_USE_ACP` (default enabled; warm persistent process mode)

On startup, TARS prewarms a standby Copilot session so the first wake/prompt can reuse an already running ACP process.

Each finalized user transcript is sent as a non-interactive prompt with session resume:

- `copilot --resume=<session-id> -p ... --output-format json`

This keeps Copilot context persistent across turns by default.
`ASSISTANT_FINAL` now means "turn complete", not "session ended".
Assistant deltas/final outputs are mapped into internal events for downstream TTS integration.

When final contract mode is enabled, bootstrap instructions require a last-line JSON object in each final message:

- `{"tars_status":"working","spoken":"..."}`
- `{"tars_status":"handoff","spoken":"..."}`

Behavior:

- `working`: TARS keeps control and auto-sends a continuation turn in the same Copilot session.
- `handoff`: TARS returns control back to user listening flow.

Voice command: saying `start new session` (also `new session`, `reset session`, `fresh session`)
resets Copilot context and creates a fresh active session.

Current routing behavior:

- STT final transcripts are only accepted while state is `LISTENING`.
- When accepted, `USER_FINAL` transitions orchestrator to `THINKING`.
- Copilot bridge sends `ASSISTANT_PARTIAL` and `ASSISTANT_FINAL` events.
- Copilot events are tagged with `session_id` + `turn_id`; stale turn events are dropped.
- `ASSISTANT_FINAL` with status `working` stays active and continues the same turn.
- `ASSISTANT_FINAL` with status `handoff` returns state to `IDLE`.

## Assistant speech output (Phase 6)

TARS now speaks assistant responses with ElevenLabs:

- `ASSISTANT_PARTIAL` text is buffered and split into speakable segments
- segments are synthesized with ElevenLabs and played through the local playback engine
- `ASSISTANT_FINAL` flushes any remaining text in the buffer
- when partial speech is enabled, already-spoken partial text is not replayed on final

Current ElevenLabs requirements:

- `ELEVENLABS_API_KEY`
- `ELEVENLABS_VOICE_ID`
- Optional quality tuning:
  - `TARS_ELEVENLABS_MODEL_ID` (default: `eleven_multilingual_v2`)
  - `TARS_ELEVENLABS_OUTPUT_FORMAT` (default: `pcm_22050`)
  - `TARS_ELEVENLABS_FALLBACK_OUTPUT_FORMATS` (default: `wav_22050,mp3_44100_128`)
  - `TARS_ELEVENLABS_STABILITY` (default: `0.45`)
  - `TARS_ELEVENLABS_SIMILARITY_BOOST` (default: `0.85`)
  - `TARS_ELEVENLABS_STYLE` (default: `0.25`)
  - `TARS_ELEVENLABS_SPEED` (default: `0.95`)
  - `TARS_ELEVENLABS_USE_SPEAKER_BOOST` (default: `1`)
  - `TARS_TTS_SPEAK_PARTIALS` (default: `1`)
  - `TARS_TTS_PARTIAL_MIN_CHARS` (default: `12`)
  - `TARS_TTS_PARTIAL_FORCE_FLUSH_CHARS` (default: `72`)

## State machine behavior (runtime contract)

States:

- `IDLE`
- `WAKE_DETECTED`
- `LISTENING`
- `THINKING`
- `SPEAKING`
- `INTERRUPTING`
- `STOPPED`

What happens in each state:

- `IDLE`
  - Wake detector is active.
  - Wake phrase match emits `WAKE`.

- `WAKE_DETECTED`
  - Orchestrator invokes wake callback.
  - Wake sound plays.
  - `READY` is emitted automatically.

- `LISTENING`
  - Wake detection is logically gated off (no retrigger while active turn/session is running).
  - VAD and STT continue capturing user speech.
  - If no speech is detected within `TARS_LISTENING_TIMEOUT_MS`, `LISTENING_TIMEOUT` returns to `IDLE`.
  - Voice cancel commands (`TARS_CANCEL_COMMANDS`, defaults: `nevermind`, `never mind`, `quit`) return to `IDLE` without sending a Copilot prompt.
  - `USER_FINAL` moves to `THINKING`.

- `THINKING`
  - Reserved for assistant processing (Copilot bridge phase).
  - `BARGE_IN` can move to `INTERRUPTING`.

- `SPEAKING`
  - Reserved for assistant audio output phase.
  - `BARGE_IN` can move to `INTERRUPTING`.
  - `ASSISTANT_FINAL` returns to `IDLE`.

- `INTERRUPTING`
  - Reserved for cancellation path.
  - `INTERRUPT_ACK` returns to `LISTENING`.

- `STOPPED`
  - Terminal state after `STOP`.

Important details:

- Wake detection is evaluated only when runtime state gate allows it (`IDLE`).
- When state is not `IDLE`, wake recognizer checks are fully skipped (not merely ignored after match).
- A retrigger cooldown (`TARS_WAKE_RETRIGGER_COOLDOWN_MS`) prevents rapid duplicate wakes.
- STT gate + de-echo run in parallel to reduce assistant self-capture.

## Run tests

```bash
pytest -q
```
