# Text-to-Speech Pipeline

Proxy converts Copilot's text responses into spoken audio using ElevenLabs, with sentence-boundary chunking for streaming playback.

## Chunking

Copilot streams word-by-word deltas as `ASSISTANT_PARTIAL` events. The chunking layer accumulates these into a buffer and splits at sentence boundaries (`.!?` or newline) once a minimum character threshold is reached (default 12 chars). A force-flush fallback emits the buffer after 72 chars without a boundary.

On `ASSISTANT_FINAL`, any remaining buffer is flushed.

## TTS queue, synthesis, and playback

Speakable segments are placed on an async synthesis queue (maxsize 64). A dedicated `_tts_synth_loop` task consumes those segments and synthesizes audio, then pushes synthesized PCM to a playback queue (maxsize 8).

1. Block the speech gate
2. Record text in the echo filter
3. Call `tts.synthesize_text(text)` — ElevenLabs REST API via `asyncio.to_thread`
4. Enqueue synthesized PCM for playback

A separate `_tts_playback_loop` task consumes the playback queue and calls `PlaybackEngine`. This lets the next chunk synthesize while the current chunk is still playing, reducing perceived latency between chunks.

The adapter tries the primary output format (`pcm_22050`), falling back to `wav_22050` on 403 errors (plan-based format restrictions).

## Thought narration

Copilot emits `agent_thought_chunk` and `tool_call` events during processing. These are logged to an activity buffer in the bridge. The user can request a spoken summary at any time by saying a status phrase (default: "what's happening" or "status"). If vanguard mode is enabled, the local model summarizes the buffer into a natural spoken sentence. Without vanguard, the raw activity log is spoken directly.

Latency fillers (short acknowledgments like "Hold on, let me check that") are spoken immediately after the user's prompt when vanguard mode is enabled, filling the silence while Copilot boots up.

## Playback

`PlaybackEngine` plays PCM audio through the default output device using `sounddevice.RawOutputStream`. Audio is written in 20ms chunks with `asyncio.sleep(0)` between writes for cooperative scheduling. Only one playback runs at a time.

## Anti self-listening integration

Before each TTS chunk plays, the speech gate is blocked and the text is recorded in the echo filter. See [Anti Self-Listening](./anti-self-listening.md).

## Interruption

When a stopword is detected, the `on_interrupt` handler cancels synthesis and playback, then drains both TTS queues.
