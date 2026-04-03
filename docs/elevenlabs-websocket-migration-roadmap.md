# ElevenLabs Realtime Streaming Migration Roadmap (No Feature Toggle)

## Goal

Completely migrate TARS text-to-speech from request/response synthesis to ElevenLabs realtime streaming over WebSockets, with no runtime toggle and no legacy fallback path.

## Current State (Baseline)

- TARS currently chunks assistant text early, but synthesis is still performed per chunk with a blocking call.
- Audio is buffered before playback, which increases time-to-first-audio and causes audible pauses between segments.
- Existing queueing and playback are optimized for segmented clips, not continuous realtime audio flow.

## Target End State

- TTS uses a single realtime streaming path only.
- Assistant text deltas are pushed incrementally to ElevenLabs.
- Audio chunks are consumed and played as they arrive.
- Interruptions immediately stop active playback and terminate the active realtime stream.
- Legacy non-streaming synthesis code is removed.

## Scope Boundaries

### In scope

- ElevenLabs realtime streaming as the only TTS transport
- Realtime text input stream to TTS
- Realtime audio output stream from TTS to playback
- Connection lifecycle, interruption handling, and observability
- Tests and documentation updates for the new single-path architecture

### Out of scope

- Runtime feature flags to choose old vs new TTS path
- Keeping legacy request/response synthesis in production code
- Multiple TTS transport modes

## Architecture Changes

## 1) TTS Adapter: Move to Realtime-Only API

Primary file: `proxy/tts/elevenlabs_adapter.py`

Changes:

1. Replace clip-based synthesis flow with a realtime session model.
2. Introduce explicit stream lifecycle methods:
   - `start_stream()`
   - `push_text(delta)`
   - `finalize_stream()`
   - `cancel_stream()`
   - `close_stream()`
3. Emit audio chunks incrementally via callback or async queue to playback.
4. Remove legacy `convert()`-style full-response synthesis path.
5. Keep strict error reporting; no silent drops.

Design notes:

- One active stream per speaking turn.
- Reconnect is explicit and bounded; fatal stream errors surface to orchestrator.
- Output format should remain PCM-compatible with existing playback path.

## 2) Orchestrator TTS Loop: Move to Incremental Push

Primary file: `proxy/main.py`

Changes:

1. Replace segment-at-a-time synthesis calls with stream control:
   - Start stream when first assistant partial arrives for a turn.
   - Push subsequent partial deltas into the active stream.
   - Finalize stream on assistant final.
2. Preserve existing speech-gate and echo-filter sequencing around active playback.
3. Convert queue semantics from "text segments awaiting full synthesis" to "realtime text deltas awaiting stream push."
4. Ensure interruption path cancels active stream and clears pending output promptly.

## 3) Playback Engine: Consume Realtime Audio Chunks

Primary file: `proxy/audio/playback.py`

Changes:

1. Add continuous chunk-consumption mode for active realtime streams.
2. Maintain single active playback ownership and deterministic cancellation behavior.
3. Keep chunk timing non-blocking and event-loop friendly.
4. Ensure audio tail is flushed correctly on finalize, and dropped on cancel.

## 4) Event and State Integration

Primary files:

- `proxy/orchestrator/*` (state/event handling)
- `proxy/main.py`

Changes:

1. Model stream lifecycle as explicit side effects tied to turn lifecycle.
2. Ensure state transitions remain deterministic when:
   - realtime stream starts late,
   - stream closes unexpectedly,
   - user interrupts during speaking.
3. Preserve invariants for turn IDs and interrupt acknowledgements.

## 5) Configuration Cleanup

Primary file: `proxy/config.py` and docs

Changes:

1. Remove settings that only support legacy non-streaming behavior.
2. Keep only settings relevant to realtime transport:
   - stream timeouts
   - keepalive/ping behavior
   - queue sizes and chunk pacing
3. Keep credential requirements unchanged where possible.

## 6) Remove Legacy Code Paths

Primary files:

- `proxy/tts/elevenlabs_adapter.py`
- `proxy/main.py`
- related tests/docs

Changes:

1. Delete old synthesis methods and dead branches.
2. Delete now-unused fallback formatting logic that only existed for old request flow.
3. Remove stale comments and docs referring to optional old path.

## Testing Plan

## Unit tests

Primary test files:

- `tests/unit/test_elevenlabs_adapter.py`
- `tests/unit/test_tts_chunking.py`
- playback/orchestrator unit tests as needed

Add or update tests for:

1. Stream lifecycle correctness (start/push/finalize/cancel/close).
2. Chunk ordering and chunk delivery to playback consumer.
3. Error propagation on stream failure.
4. Interruption semantics during active stream.
5. No duplicate speech across partial + final handling.

## Integration tests

Add or update integration coverage for:

1. End-to-end partial text -> live audio start.
2. Mid-turn interruption during realtime output.
3. Stream recovery from transient network faults.
4. Long responses with continuous chunk flow.

## Acceptance Criteria

Migration is complete when all are true:

1. TTS path uses realtime streaming only; no old synthesis route remains.
2. First audible response starts from partial output, without waiting for full assistant final.
3. Interruptions stop realtime audio promptly and return control to listening.
4. No silent message/audio loss in normal operation.
5. Docs and tests reflect only the new architecture.

## Rollout Strategy (Codebase-Level, No Runtime Toggle)

1. Implement migration on a dedicated branch.
2. Land in coherent phases (adapter, orchestrator, playback, cleanup, tests, docs).
3. Merge only after full test pass for updated suite.
4. Use git revert as rollback mechanism if needed; no runtime path split in shipped code.

## Work Breakdown

1. Realtime adapter refactor and lifecycle API.
2. Orchestrator rewrite for incremental stream push.
3. Playback realtime chunk consumption.
4. Interrupt and cancellation hardening.
5. Legacy path removal.
6. Test updates and coverage expansion.
7. Documentation updates and final cleanup.
