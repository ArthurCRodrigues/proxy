# Text-to-Speech Pipeline

Proxy converts Copilot's text responses into spoken audio using a realtime streaming pipeline over ElevenLabs WebSocket. The pipeline has three stages: text streaming, synthesis streaming, and playback streaming.

## Streaming text flow

Copilot streams response deltas as `ASSISTANT_PARTIAL` events. Each partial is enqueued onto a single ordered TTS command queue and pushed to the active ElevenLabs stream in order.

### How it works

1. On first outbound text for a turn, Proxy starts playback streaming and opens an ElevenLabs WebSocket stream.
2. Each partial delta is sent with `push_text(...)`.
3. On `ASSISTANT_FINAL`, Proxy sends `finalize_stream()` to flush tail audio.
4. On cancel/interrupt, Proxy cancels the active stream and playback immediately.

## TTS command queue

Outbound text commands are processed by a single worker queue (`PROXY_TTS_TEXT_QUEUE_MAXSIZE`, default `128`). This guarantees in-order delivery and avoids race conditions from per-partial task spawning.

If the queue saturates, Proxy logs an error, interrupts the active stream, drains stale commands, and continues from fresh state.

## ElevenLabs synthesis

`ElevenLabsTTSAdapter` maintains one WebSocket stream per speaking turn. Incoming audio packets are base64-decoded and forwarded to playback as they arrive.

### Voice settings

| Setting | Config | Default |
|---|---|---|
| Voice ID | `ELEVENLABS_VOICE_ID` | (required) |
| Model | `PROXY_ELEVENLABS_MODEL_ID` | `eleven_multilingual_v2` |
| Output format | `PROXY_ELEVENLABS_OUTPUT_FORMAT` | `pcm_22050` |
| Latency mode | `PROXY_ELEVENLABS_LATENCY_MODE` | `optimistic` |
| Stability | `PROXY_ELEVENLABS_STABILITY` | `0.45` |
| Similarity boost | `PROXY_ELEVENLABS_SIMILARITY_BOOST` | `0.85` |
| Style | `PROXY_ELEVENLABS_STYLE` | `0.65` |
| Speed | `PROXY_ELEVENLABS_SPEED` | `0.95` |
| Speaker boost | `PROXY_ELEVENLABS_USE_SPEAKER_BOOST` | `true` |

### Stream lifecycle

- `start_stream()` opens WebSocket and starts listener.
- `push_text(delta)` sends incremental text.
- `finalize_stream()` flushes and waits for final audio.
- `cancel_stream()` aborts stream and closes transport.
- `close_stream()` is an alias for cancellation/cleanup.

## Playback

`PlaybackEngine` consumes realtime PCM chunks from an async queue (`PROXY_TTS_AUDIO_QUEUE_MAXSIZE`, default `256`) and writes directly to `sounddevice.RawOutputStream`.

Only one stream playback can be active at a time. Starting a new stream cancels any previous one.
