# Anti Self-Listening

Proxy speaks through the same environment where its microphone listens. Three layers prevent it from transcribing its own voice.

## Layer 1: State-based gating

STT audio forwarding is gated by orchestrator state. The `_allow_stt_audio_forward` callback only returns True when the state is LISTENING. During THINKING, SPEAKING, or IDLE, audio isn't sent to Deepgram at all. This is the coarsest and most reliable layer.

## Layer 2: Speech gate

The `SpeechGate` is a time-based lock. When TTS playback starts, `speech_gate.block()` sets a hold window (default 900ms). During this window, both audio forwarding and transcript acceptance are blocked. This catches the transition edge where state changes but audio is still playing.

## Layer 3: Echo filter

The `EchoFilter` maintains a sliding window of recent assistant text (last 6 seconds, up to 12 entries). When an STT transcript arrives, it's compared against the window using exact match or `SequenceMatcher` fuzzy match (threshold 0.78). Matches are rejected as echoes.

Everything Proxy speaks is recorded in the filter: TTS chunks, the word "yes" during wake sounds, and all assistant partial/final text.

## Stopword detection

The stopword detector (Vosk) operates independently of all three layers. It processes raw audio from the microphone regardless of state, speech gate, or echo filter. This ensures "stop" is always heard even while Proxy is speaking.
