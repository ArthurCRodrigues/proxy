# Speech-to-Text (Deepgram)

Proxy uses Deepgram for real-time speech-to-text over a persistent WebSocket connection.

## Connection

The WebSocket connects to `wss://api.deepgram.com/v1/listen` with query parameters for model, language, endpointing, utterance end timeout, punctuation, smart formatting, and keyterms. The connection opens during startup and stays alive for the process lifetime, with automatic reconnection on failure.

## Transcript flow

Deepgram sends three types of relevant messages:

**Interim partials** (`is_final=false, speech_final=false`) — ongoing recognition guesses. Forwarded to `on_partial` for UI/timeout purposes only. Never used for prompt building.

**Finalized segments** (`is_final=true, speech_final=false`) — a segment of audio has been finalized and won't change. Appended to `_finalized_segments` list. Not emitted as a final transcript.

**UtteranceEnd** (`type: "UtteranceEnd"`) — Deepgram has determined the speaker is done. The adapter joins all accumulated `_finalized_segments` with spaces and fires `on_final`. This is what triggers the LISTENING → THINKING transition.

**speech_final** (`speech_final=true`) — alternative end-of-speech signal. If received, segments are joined and emitted immediately (same as UtteranceEnd).

## Why finalized segments?

Deepgram's `is_final` segments are the source of truth. Each covers a specific audio window and won't be revised. By accumulating only these and joining on UtteranceEnd, the adapter produces clean transcripts without the duplication issues that come from merging overlapping partial results.

## Reconnection

If the WebSocket drops, the adapter retries with linear backoff (base delay × attempt number), up to `reconnect_max_attempts` (default 3). This handles Deepgram idle timeouts that occur when Proxy is in THINKING/SPEAKING and not sending audio.

## Configuration

| Setting | Default | Purpose |
|---|---|---|
| `PROXY_DEEPGRAM_MODEL` | `nova-3` | Recognition model |
| `PROXY_DEEPGRAM_LANGUAGE` | `en-US` | Language |
| `PROXY_DEEPGRAM_UTTERANCE_END_MS` | `3500` | Silence before UtteranceEnd fires |
| `PROXY_DEEPGRAM_KEYTERMS` | (empty) | Domain-specific terms to boost |
