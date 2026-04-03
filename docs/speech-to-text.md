# Speech-to-Text (Deepgram)

Proxy uses [Deepgram](https://deepgram.com/) for real-time speech-to-text transcription over a persistent websocket connection. The `DeepgramSTTAdapter` manages the connection lifecycle, audio streaming, and transcript assembly.

## Connection lifecycle

The websocket connects to `wss://api.deepgram.com/v1/listen` with query parameters derived from configuration:

| Parameter | Config | Default |
|---|---|---|
| `model` | `PROXY_DEEPGRAM_MODEL` | `nova-3` |
| `language` | `PROXY_DEEPGRAM_LANGUAGE` | `en-US` |
| `encoding` | (hardcoded) | `linear16` |
| `sample_rate` | `PROXY_AUDIO_SAMPLE_RATE` | `16000` |
| `channels` | (hardcoded) | `1` |
| `interim_results` | `PROXY_DEEPGRAM_INTERIM_RESULTS` | `true` |
| `endpointing` | `PROXY_DEEPGRAM_ENDPOINTING_MS` | `700` (or `false` if disabled) |
| `utterance_end_ms` | `PROXY_DEEPGRAM_UTTERANCE_END_MS` | `3500` |
| `punctuate` | `PROXY_DEEPGRAM_PUNCTUATE` | `true` |
| `smart_format` | `PROXY_DEEPGRAM_SMART_FORMAT` | `true` |
| `keyterm` | `PROXY_DEEPGRAM_KEYTERMS` | (empty) |

The connection is opened once during `WakeVadEngine.start()` and stays open for the lifetime of the process. Audio chunks are pushed via `push_audio(data)` whenever the STT gate allows it.

Keyterms are domain-specific words or phrases that Deepgram should prioritize in recognition (e.g. project names, technical terms). They're passed as repeated `keyterm` query parameters.

## Transcript flow

Deepgram sends JSON messages over the websocket. The adapter processes `Results` messages, which contain:

- `transcript` — the recognized text.
- `is_final` — Deepgram considers this segment finalized.
- `speech_final` — Deepgram detected end of speech (via its own VAD).

The adapter classifies each message as either a **partial** (interim result) or a **final** (complete utterance).

### Partial handling

Every non-final transcript is:
1. Stored as `_last_partial_text` (the raw latest partial).
2. Merged into `_assembled_partial_text` using overlap-aware concatenation.
3. Forwarded to the `on_partial` callback.

The merge logic (`_merge_partial_utterance`) handles the fact that Deepgram's partial results can overlap — a new partial might repeat the tail of the previous one. The algorithm:
- If the new partial is contained within the assembled text, keep the assembled text.
- If the assembled text is contained within the new partial, use the new partial.
- Otherwise, find the longest token-level suffix-prefix overlap and merge without duplication.
- Fall back to simple concatenation if no overlap is found.

### Final handling and the finalization gate

This is the most nuanced part of the adapter. There are two sources of final transcripts:

1. **Solicited finals** — triggered by Proxy's local VAD calling `end_utterance()`, which sends a `Finalize` command to Deepgram. The adapter sets `_finalize_requested = True` before sending.
2. **Unsolicited finals** — Deepgram's own endpointing decides the utterance is complete, or `speech_final` is set.

The adapter treats these differently:

**Solicited finals and `speech_final` results** are always accepted. The text is assembled via `_assemble_final_text`, state is reset, and the `on_final` callback fires.

**Unsolicited finals** (where `_finalize_requested` is False and `speech_final` is False) are gated. The adapter checks:
- Has the last partial been stable (unchanged) for at least `_unsolicited_final_hold_s` seconds? (This value is derived from `utterance_end_ms`, minimum 1 second.)
- Does the final text match or contain the stable partial?

If both conditions are met, the final is accepted. Otherwise, it's demoted to a partial — the `on_partial` callback is called instead of `on_final`. This prevents Deepgram's endpointing from prematurely finalizing a transcript while the user is still mid-sentence but pausing briefly.

### Final text assembly

When a final is accepted, `_assemble_final_text` tries to produce the best possible transcript:

1. Uses the final text from Deepgram, falling back to the last partial, then the assembled partial history.
2. Compares the candidate against the assembled partial history. If the assembled version has ≥2 extra words and contains the candidate as a subset, the assembled version is preferred — it may have captured words that Deepgram dropped between partial windows.

## Reconnection

If the websocket connection drops unexpectedly, the adapter attempts reconnection with linear backoff:

```
attempt 1: wait base_delay_ms * 1 (default 200ms)
attempt 2: wait base_delay_ms * 2 (default 400ms)
attempt 3: wait base_delay_ms * 3 (default 600ms)
```

After `PROXY_DEEPGRAM_RECONNECT_MAX_ATTEMPTS` (default 3) failures, reconnection is abandoned and the error is logged. The adapter will not receive audio until the next `start_stream()` call.

## Interaction with the VAD

The adapter does not make its own end-of-speech decisions. It relies on the `WakeVadEngine` to call `end_utterance()` when the local RMS-based VAD detects silence. This sends a `Finalize` command to Deepgram, which responds with a final transcript.

Deepgram's own endpointing (`endpointing_ms`) is still enabled as a secondary mechanism, but unsolicited finals from it are subject to the stability gate described above.
