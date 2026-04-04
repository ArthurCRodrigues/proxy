# ElevenLabs WebSocket Migration Roadmap

Date: 2026-04-03

## Motivation

The current TTS implementation uses the ElevenLabs REST API (`text_to_speech.convert`) synchronously per chunk. Each chunk requires a full HTTP round-trip: connect, send text, wait for the entire audio response, then play. This means:

- **High latency per chunk.** Every sentence-boundary chunk pays a full HTTP request/response cycle.
- **No streaming playback.** Audio can only start playing after the entire chunk is synthesized and downloaded.
- **Blocking serialization.** The `asyncio.Lock` ensures only one synthesis runs at a time, and `asyncio.to_thread` blocks a thread pool slot for the duration.
- **Client recreation.** A new `ElevenLabs` client is instantiated on every call.

The WebSocket API (`/v1/text-to-speech/{voice_id}/stream-input`) solves all of these by maintaining a persistent connection where text is streamed in and audio chunks are streamed back incrementally.

## Current architecture

```
Copilot partial deltas
    │
    ▼
chunking.py (sentence boundary splitting)
    │
    ▼
tts_queue (asyncio.Queue, maxsize=64)
    │
    ▼
_tts_loop (sequential consumer)
    │
    ├─ tts.synthesize_text(chunk)  ← REST API, blocks until full audio returned
    │
    ▼
PlaybackEngine.play_pcm(audio)   ← plays complete chunk, then next
```

Each chunk goes through: text → REST call → full audio bytes → playback. Chunks are processed sequentially.

## Target architecture

```
Copilot partial deltas
    │
    ▼
ElevenLabs WebSocket (persistent connection)
    │
    ├─ send: {"text": delta}           ← stream text in as it arrives
    ├─ send: {"text": "", "flush": true} ← on ASSISTANT_FINAL
    │
    ▼
    receive: {"audio": "<base64>"}     ← audio chunks arrive incrementally
    │
    ▼
PlaybackEngine (continuous stream)     ← plays audio as it arrives
```

Text flows directly into the WebSocket as Copilot produces it. Audio flows back and into the speaker as ElevenLabs produces it. No batching, no sentence-boundary chunking, no queue.

## Migration plan

### Phase 1: WebSocket adapter

Replace `ElevenLabsTTSAdapter` with a WebSocket-based implementation.

**Connection lifecycle:**
- Open a WebSocket to `wss://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream-input?model_id={model_id}&output_format={format}`.
- Send an initialization message with voice settings, generation config, and API key.
- Keep the connection alive across multiple utterances (the connection auto-closes after 20s of inactivity — send a space `" "` as a keepalive if needed).
- On shutdown or cancel, send `{"text": ""}` to close gracefully.

**New public interface:**
```python
async def connect(self) -> None
async def send_text(self, text: str) -> None      # stream text in
async def flush(self) -> None                      # force-generate buffered text
async def close(self) -> None                      # close connection
```

Audio arrives asynchronously via a listener task that reads from the WebSocket, base64-decodes audio chunks, and feeds them to a callback or queue for playback.

**Reconnection:** If the WebSocket drops, reconnect transparently. Buffer any text sent during reconnection and replay it.

### Phase 2: Remove chunking layer

With WebSocket streaming, ElevenLabs handles its own internal buffering via `chunk_length_schedule`. Proxy no longer needs to split text at sentence boundaries.

**Remove:**
- `proxy/tts/chunking.py` — the entire file (`append_partial`, `merge_final`, `split_speakable_segments`, `consume_speakable_segments`).
- `tts_queue` in `main.py` — no more intermediate text queue.
- `_tts_loop` in `main.py` — no more sequential chunk consumer.
- `tts_text_buffer` and `tts_partial_seen_since_final` state in `main.py`.
- Config fields: `tts_partial_min_chars`, `tts_partial_force_flush_chars`.
- The `PROXY_TTS_SPEAK_PARTIALS` toggle becomes unnecessary — streaming is always on.

**Replace with direct forwarding:**
- `_on_assistant_partial(text)` → `tts.send_text(text)` (stream each delta directly into the WebSocket).
- `_on_assistant_final(text)` → `tts.flush()` (force-generate any remaining buffered text).

### Phase 3: Streaming playback

The current `PlaybackEngine` expects a complete `PcmAudio` object. With WebSocket TTS, audio arrives in small base64-encoded chunks while synthesis is ongoing.

**Modify `PlaybackEngine`:**
- Keep a single `RawOutputStream` open for the duration of an utterance.
- Accept audio chunks incrementally (via a queue or async iterator).
- Write each chunk to the stream as it arrives.
- Close the stream when the utterance is complete (signaled by `isFinal` from ElevenLabs).

The wake sound playback (`play_pcm` for WAV files) should remain as-is — it's a one-shot local file, not a streaming operation.

### Phase 4: Configuration cleanup

**Remove:**
- `PROXY_TTS_SPEAK_PARTIALS` — always streaming.
- `PROXY_TTS_PARTIAL_MIN_CHARS` — ElevenLabs handles buffering via `chunk_length_schedule`.
- `PROXY_TTS_PARTIAL_FORCE_FLUSH_CHARS` — replaced by `flush: true` on final.
- `PROXY_ELEVENLABS_FALLBACK_OUTPUT_FORMATS` — WebSocket format is set at connection time, no per-request fallback needed.

**Add:**
- `PROXY_ELEVENLABS_CHUNK_LENGTH_SCHEDULE` — controls ElevenLabs' internal buffering (default: `120,160,250,290`). Lower values = lower latency but potentially lower quality.

**Keep:**
- All voice settings (stability, similarity_boost, style, speed, speaker_boost) — sent in the initialization message.
- `PROXY_ELEVENLABS_MODEL_ID` — note that `eleven_flash_v2_5` is recommended for low-latency WebSocket use. `eleven_v3` does not support WebSockets.
- `PROXY_ELEVENLABS_OUTPUT_FORMAT` — set as a query parameter on the WebSocket URL.

### Phase 5: Anti self-listening adjustments

The speech gate currently blocks on every `synthesize_text` call. With streaming:
- Block the speech gate when the first audio chunk arrives from the WebSocket (not when text is sent).
- The echo filter records text as it's sent — this can stay as-is since `send_text` is called with each delta.

## Key ElevenLabs WebSocket behaviors to account for

1. **Buffering threshold.** ElevenLabs won't generate audio until enough text accumulates (controlled by `chunk_length_schedule`). Short text fragments may sit in the buffer until more text arrives or `flush` is called.

2. **Flush.** Sending `{"text": "...", "flush": true}` forces immediate generation of all buffered text. Use this on `ASSISTANT_FINAL`.

3. **Close signal.** Sending `{"text": ""}` (empty string) closes the connection and flushes remaining text. A space `" "` keeps it alive.

4. **20-second idle timeout.** The connection closes after 20s of no messages. Send keepalives during idle periods if the connection should persist across wake cycles.

5. **Audio format.** Returned as base64-encoded chunks in `{"audio": "..."}` messages. The `isFinal` field signals the last chunk.

6. **Model restriction.** `eleven_v3` does not support WebSockets. Use `eleven_flash_v2_5` or `eleven_multilingual_v2`.

## Execution order

1. Phase 1 (WebSocket adapter) — can be developed and tested in isolation.
2. Phase 3 (streaming playback) — needed before Phase 1 can be integrated.
3. Phase 2 (remove chunking) — only after Phases 1+3 are working end-to-end.
4. Phase 4 (config cleanup) — after Phase 2.
5. Phase 5 (anti self-listening) — minor adjustment, do alongside Phase 2.

## Files affected

| File | Action |
|---|---|
| `proxy/tts/elevenlabs_adapter.py` | Rewrite: REST → WebSocket |
| `proxy/tts/chunking.py` | Delete entirely |
| `proxy/audio/playback.py` | Extend: add streaming chunk playback |
| `proxy/main.py` | Simplify: remove tts_queue, _tts_loop, chunking imports, buffer state |
| `proxy/config.py` | Remove chunking configs, add chunk_length_schedule |
| `.env.example` | Update accordingly |
| `tests/unit/test_tts_chunking.py` | Delete entirely |
| `tests/unit/test_elevenlabs_adapter.py` | Rewrite for WebSocket interface |
