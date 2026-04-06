# Wake Word & Stopword Detection

The `WakeVadEngine` is the always-on component that listens for the wake phrase and stopword. It runs as a single async task processing audio chunks from the microphone.

## How it works

Every audio chunk from `AudioIO` is fed to a local Vosk `KaldiRecognizer`. On each recognized result, two checks run:

1. **Stopword check** (active during THINKING/SPEAKING) — if the recognized text contains a stopword phrase, publish an `INTERRUPT` event.
2. **Wake check** (active during IDLE) — if the recognized text contains the wake phrase, publish a `WAKE` event.

These are mutually exclusive by state. The same Vosk recognizer handles both.

## Wake word detection

Vosk processes audio locally with zero cloud calls. Recognition results are checked against configured wake phrases using word-boundary regex (`\b{phrase}\b`), preventing false positives from words containing the wake phrase as a substring.

Wake phrases are configured as a comma-separated list via `PROXY_WAKE_ALIASES`. The primary `PROXY_WAKE_PHRASE` is automatically prepended if not already in the list.

### Gating and cooldowns

- **State gate** — Wake detection only fires in IDLE state.
- **Arming latch** — After a wake fires, the latch disarms. Re-arms when the system returns to IDLE.
- **Rearm guard** (1200ms default) — Delay after returning to IDLE before wake detection activates. Prevents Proxy's own TTS from re-triggering.
- **Retrigger cooldown** (1500ms default) — Minimum interval between consecutive wake events.
- **Recognizer reset** — Vosk recognizer is reset on state transitions to clear stale audio.

## Stopword detection

The stopword uses the same Vosk recognizer and the same word-boundary matching. It fires during THINKING or SPEAKING states.

When detected:
1. `INTERRUPT` event is published
2. Orchestrator calls `on_interrupt()` which cancels the Copilot turn, stops TTS playback, and drains the TTS queue
3. State transitions to LISTENING — user can speak their next prompt

Configuration:
- `PROXY_STOPWORD_ALIASES` — comma-separated stopword phrases (default: `stop,shut up`)
- `PROXY_STOPWORD_COOLDOWN_MS` — minimum interval between stopword triggers (default: 1500ms)

## Audio forwarding to STT

Audio chunks are forwarded to Deepgram only when the orchestrator is in LISTENING state and the speech gate allows it. This gating ensures Deepgram only receives audio during the active listening window.
