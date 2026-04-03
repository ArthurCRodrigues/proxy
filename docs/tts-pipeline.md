# Text-to-Speech Pipeline

Proxy converts Copilot's text responses into spoken audio using a streaming pipeline that begins speaking before the full response is available. The pipeline has three stages: chunking, synthesis, and playback.

## Streaming chunking

Copilot streams its response as a series of partial text deltas. These arrive as `ASSISTANT_PARTIAL` events, each containing a small fragment of text (often just a few words). The chunking layer accumulates these fragments and splits them into speakable segments at natural boundaries.

### How it works

A text buffer accumulates incoming deltas via `append_partial(buffer, delta)`. After each append, `consume_speakable_segments` scans the buffer for sentence boundaries — periods, exclamation marks, question marks, or newlines.

A segment is emitted when:
1. A sentence boundary is found at or after `min_chars` characters (default 12, configurable via `PROXY_TTS_PARTIAL_MIN_CHARS`).
2. OR the buffer exceeds `force_flush_chars` (default 72, configurable via `PROXY_TTS_PARTIAL_FORCE_FLUSH_CHARS`) without any boundary — the entire buffer is flushed as-is. This prevents long boundaryless runs (e.g. a single very long sentence) from blocking speech output indefinitely. Setting this to `0` disables force-flushing.

The consumed text is removed from the buffer, and the remaining text carries over for the next delta.

### Final flush

When `ASSISTANT_FINAL` arrives, the buffer is flushed with `force=True`, which emits all remaining text regardless of boundaries. This ensures nothing is left unspoken.

### Deduplication with merge_final

If `tts_speak_partials` is enabled (the default) and partials were seen, the final flush only processes whatever remains in the buffer — most of the text has already been spoken via partial chunks.

If no partials were seen (e.g. `tts_speak_partials` is disabled, or Copilot returned the entire response in one shot), `merge_final` deduplicates the final text against the buffer using normalized substring matching to avoid speaking the same content twice.

## TTS queue

Speakable segments are placed on an async queue (`maxsize=64`). A dedicated `_tts_loop` task consumes from this queue and processes each segment sequentially:

1. Blocks the speech gate (see [Anti Self-Listening](./anti-self-listening.md)).
2. Records the text in the echo filter.
3. Calls `tts.synthesize_text(text)` to get PCM audio.
4. Plays the audio via `PlaybackEngine`.

If the queue is full (64 segments backed up), new segments are dropped with a debug log. This provides backpressure without blocking the Copilot response stream.

## ElevenLabs synthesis

The `ElevenLabsTTSAdapter` calls the ElevenLabs API to convert text to speech. Each call creates a fresh client instance and runs the synchronous SDK call in a thread via `asyncio.to_thread`.

### Voice settings

| Setting | Config | Default |
|---|---|---|
| Voice ID | `ELEVENLABS_VOICE_ID` | (required) |
| Model | `PROXY_ELEVENLABS_MODEL_ID` | `eleven_multilingual_v2` |
| Output format | `PROXY_ELEVENLABS_OUTPUT_FORMAT` | `pcm_22050` |
| Stability | `PROXY_ELEVENLABS_STABILITY` | `0.45` |
| Similarity boost | `PROXY_ELEVENLABS_SIMILARITY_BOOST` | `0.85` |
| Style | `PROXY_ELEVENLABS_STYLE` | `0.25` |
| Speed | `PROXY_ELEVENLABS_SPEED` | `0.95` |
| Speaker boost | `PROXY_ELEVENLABS_USE_SPEAKER_BOOST` | `true` |

### Output format fallback

The adapter tries the primary output format first. If ElevenLabs returns a 403 error (format not available on the current plan), it falls back to the formats listed in `PROXY_ELEVENLABS_FALLBACK_OUTPUT_FORMATS` (default: `wav_22050`).

For `pcm_*` formats, the sample rate is parsed from the format string (e.g. `pcm_22050` → 22050 Hz). For `wav_*` formats, the WAV header is read to extract sample rate, channels, and sample width.

### Cancellation

Cancellation is cooperative. Setting `_cancelled = True` causes the adapter to return empty audio after the current synthesis call completes. The lock ensures only one synthesis runs at a time.

## Playback

The `PlaybackEngine` plays PCM audio through the system's default output device using `sounddevice.RawOutputStream`. Audio is written in 20ms chunks with `asyncio.sleep(0)` between writes to yield to the event loop.

Only one playback can be active at a time. Starting a new playback cancels the previous one.

## Disabling streaming speech

Set `PROXY_TTS_SPEAK_PARTIALS=0` to disable streaming. In this mode, no speech is produced until `ASSISTANT_FINAL` arrives, and the entire response is spoken at once. This increases latency but may be preferred for short, predictable responses.
