# Anti Self-Listening

Proxy speaks its responses aloud through the same physical environment where its microphone is listening. Without protection, it would transcribe its own TTS output and treat it as user input — creating a feedback loop. Two complementary mechanisms prevent this.

## Speech gate

The `SpeechGate` is a time-based lock. When Proxy starts speaking (either a wake acknowledgment sound or a TTS chunk), it calls `speech_gate.block()`, which sets a hold window of `PROXY_STT_GATE_HOLD_MS` milliseconds (default 900ms).

During this window, `speech_gate.allow()` returns `False`. Two things check this gate:

1. **Audio forwarding gate** (`_allow_stt_audio_forward`) — prevents raw audio chunks from being sent to Deepgram while the gate is blocked. This means Deepgram doesn't even receive the audio of Proxy's own voice.
2. **Transcript acceptance** (`_accept_transcript`) — rejects any STT results that arrive while the gate is blocked, as a second line of defense.

The hold window is intentionally longer than the typical TTS chunk duration to account for audio propagation delay and Deepgram's processing latency.

### When the gate is activated

- Before playing the wake acknowledgment sound.
- As each realtime TTS audio chunk arrives before enqueueing to playback.

## Echo filter

The `EchoFilter` is a content-based filter that catches self-listening that slips past the speech gate — for example, if the microphone picks up the tail end of a TTS chunk after the time window expires.

It maintains a sliding window of recent assistant text (last 6 seconds, up to 12 entries). When a new STT transcript arrives, the filter compares it against every entry in the window using two checks:

1. **Exact match** — the normalized transcript is identical to a recent assistant utterance.
2. **Fuzzy match** — `difflib.SequenceMatcher.ratio()` between the transcript and a recent utterance exceeds `PROXY_STT_DEECHO_SIMILARITY_THRESHOLD` (default 0.78).

If either check passes, the transcript is classified as an echo and rejected.

### What gets recorded

Every piece of text that Proxy speaks is recorded in the echo filter:
- The word "yes" (recorded when the wake sound plays, since the wake sound is an acknowledgment).
- Each assistant partial and final text as it arrives from Copilot.

This redundancy ensures the filter has coverage even if text is chunked differently between the Copilot response and the TTS output.

### Normalization

Both the candidate transcript and the stored assistant text are normalized before comparison: lowercased, stripped, and whitespace-collapsed. This makes the comparison resilient to minor transcription differences.

## State-based gating

Beyond the two filters, STT is also gated by the orchestrator state. The `_allow_stt_audio_forward` callback only returns `True` when the state is `LISTENING`. Since Proxy is in `SPEAKING` (or `THINKING`, or `IDLE`) while TTS is playing, audio simply isn't forwarded to Deepgram during those states.

This is the coarsest and most reliable layer of protection. The speech gate and echo filter exist as defense-in-depth for edge cases around state transitions.

## Configuration

| Setting | Default | Purpose |
|---|---|---|
| `PROXY_STT_GATE_ENABLED` | `1` | Enable/disable the speech gate entirely |
| `PROXY_STT_GATE_HOLD_MS` | `900` | How long to block STT after TTS starts |
| `PROXY_STT_DEECHO_ENABLED` | `1` | Enable/disable the echo filter |
| `PROXY_STT_DEECHO_SIMILARITY_THRESHOLD` | `0.78` | Minimum SequenceMatcher ratio to classify as echo |

Both mechanisms can be independently disabled for debugging, though this is not recommended in normal operation.
