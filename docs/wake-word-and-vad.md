# Wake Word Detection & Voice Activity Detection

The `WakeVadEngine` is the always-on component that listens for the wake phrase and detects when the user starts and stops speaking. It runs as a single async task that processes audio chunks from the microphone in a tight loop.

## Architecture

The engine sits between the microphone (`AudioIO`) and two consumers:

1. **Vosk recognizer** — a local speech model used exclusively for wake word detection.
2. **Deepgram STT** — the cloud transcription service, which only receives audio when the orchestrator is in `LISTENING` state.

Every audio chunk passes through both paths simultaneously. Vosk runs locally with zero latency. Deepgram receives chunks conditionally, gated by the orchestrator state and the speech gate.

## Wake word detection

Proxy uses a [Vosk](https://alphacephei.com/vosk/) `KaldiRecognizer` for offline wake word detection. The recognizer processes every audio chunk and produces either a full result (when it believes a complete utterance has ended) or a partial result (ongoing recognition).

The engine checks both result types against the configured wake phrases using word-boundary regex matching (`\b{phrase}\b`). This prevents false positives from words that contain the wake phrase as a substring (e.g. "guitars" won't trigger "tars").

Wake phrases are configured as a comma-separated list via `PROXY_WAKE_ALIASES`. The primary `PROXY_WAKE_PHRASE` is automatically prepended if not already in the list. Multiple aliases help catch common misrecognitions of the wake word by the local model.

Partial matching (checking Vosk partial results in addition to full results) is disabled by default (`PROXY_WAKE_MATCH_PARTIAL=0`) because it increases false positive rates. It can be enabled for environments where the full-result path is too slow.

### Gating and cooldowns

The wake engine has several layers of protection against spurious triggers:

**State gate (`wake_enabled`):** A callback tied to the orchestrator — wake detection is only active when the state machine is in `IDLE`. While Proxy is listening, thinking, or speaking, wake events are suppressed.

**Arming latch (`_wake_armed`):** After a wake event fires, the latch disarms. It re-arms only when the system leaves and re-enters `IDLE`. This prevents the same audio from triggering multiple wake events.

**Rearm guard (`PROXY_WAKE_REARM_GUARD_MS`, default 1200ms):** After the system returns to `IDLE`, there's a configurable delay before wake detection becomes active again. This prevents Proxy's own TTS output (which may contain the wake word) from immediately re-triggering.

**Retrigger cooldown (`PROXY_WAKE_RETRIGGER_COOLDOWN_MS`, default 1500ms):** A minimum interval between consecutive wake events, regardless of state transitions.

**Recognizer reset:** When the orchestrator state changes (entering or leaving `IDLE`), the Vosk recognizer is reset. This clears any buffered audio that might contain stale speech from a previous interaction.

## Voice Activity Detection (VAD)

The `VADTracker` is a simple RMS-based energy detector that determines when the user is speaking:

```
Speech starts when: RMS ≥ vad_start_rms (default 600.0)
Speech ends when:   RMS ≤ vad_end_rms (default 350.0) for vad_end_silence_ms (default 700ms)
```

The VAD serves one critical purpose: **triggering Deepgram finalization**. When the VAD detects end-of-speech (sustained silence after speech), it calls `stt.end_utterance()`, which sends a `Finalize` command to Deepgram over the websocket. This tells Deepgram to emit its final transcript for the current utterance.

This local VAD-driven finalization is used instead of relying solely on Deepgram's built-in endpointing because:
- It gives Proxy direct control over when an utterance is considered complete.
- The RMS thresholds can be tuned for the specific microphone and environment.
- It decouples the "end of speech" decision from the cloud service's latency.

The VAD thresholds are configurable:
- `PROXY_VAD_START_RMS` — minimum RMS to begin speech detection.
- `PROXY_VAD_END_RMS` — maximum RMS to count as silence.
- `PROXY_VAD_END_SILENCE_MS` — how long silence must persist before triggering end-of-speech.

## Audio forwarding to STT

Audio chunks are forwarded to Deepgram only when two conditions are met:

1. The `stt_gate_allow` callback returns `True` — this checks that the orchestrator is in `LISTENING` state and the speech gate isn't blocking (see [Anti Self-Listening](./anti-self-listening.md)).
2. The STT adapter reports `ready()` — meaning the websocket connection is open.

This gating ensures Deepgram only receives audio during the active listening window, not during wake detection, TTS playback, or idle periods.

## Debug modes

Two debug flags help with tuning:

- `PROXY_WAKE_DEBUG_TRANSCRIPTS=1` — logs every Vosk recognition result (full and partial), useful for understanding what the local model is hearing.
- `PROXY_WAKE_DEBUG_RMS=1` — logs the RMS value of every audio chunk, useful for calibrating VAD thresholds for a specific microphone.
