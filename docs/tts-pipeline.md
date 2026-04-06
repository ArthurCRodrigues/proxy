# Text-to-Speech Pipeline

Proxy converts Copilot's text responses into spoken audio using ElevenLabs, with sentence-boundary chunking for streaming playback.

## Chunking

Copilot streams word-by-word deltas as `ASSISTANT_PARTIAL` events. The chunking layer accumulates these into a buffer and splits at sentence boundaries (`.!?` or newline) once a minimum character threshold is reached (default 12 chars). A force-flush fallback emits the buffer after 72 chars without a boundary.

On `ASSISTANT_FINAL`, any remaining buffer is flushed.

## TTS queue and synthesis

Speakable segments are placed on an async queue (maxsize 64). A dedicated `_tts_loop` task consumes segments sequentially:

1. Block the speech gate
2. Record text in the echo filter
3. Call `tts.synthesize_text(text)` — ElevenLabs REST API via `asyncio.to_thread`
4. Play the returned PCM audio via `PlaybackEngine`

The adapter tries the primary output format (`pcm_22050`), falling back to `wav_22050` on 403 errors (plan-based format restrictions).

## Thought narration

When Copilot emits `agent_thought_chunk` events (e.g. "Reviewing technical debt", "Exploring codebase"), the bridge fires an `on_narration` callback that enqueues the thought text into the same TTS queue. Consecutive duplicate thoughts are suppressed.

## Playback

`PlaybackEngine` plays PCM audio through the default output device using `sounddevice.RawOutputStream`. Audio is written in 20ms chunks with `asyncio.sleep(0)` between writes for cooperative scheduling. Only one playback runs at a time.

## Anti self-listening integration

Before each TTS chunk plays, the speech gate is blocked and the text is recorded in the echo filter. See [Anti Self-Listening](./anti-self-listening.md).

## Interruption

When a stopword is detected, the `on_interrupt` handler cancels playback and drains the TTS queue. The in-flight `synthesize_text` call completes naturally but its output is discarded.
