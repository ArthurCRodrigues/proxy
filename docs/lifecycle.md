# Lifecycle

How Proxy boots, processes a voice interaction, and shuts down.

## Startup

1. Load settings from `.env` and environment variables.
2. Create all components: EventBus, AudioIO, PlaybackEngine, DeepgramSTTAdapter, ElevenLabsTTSAdapter, SpeechGate, EchoFilter.
3. Register STT callbacks (`_on_partial`, `_on_final`).
4. Create CopilotBridge with assistant partial/final/narration callbacks.
5. Create SessionPool, ensure active session (prewarm + background bootstrap).
6. Start TTS loop task.
7. Create Orchestrator with wake and interrupt callbacks.
8. Start WakeVadEngine (opens microphone, loads Vosk model, begins audio loop).
9. Enter IDLE state, listening for wake word.

## A complete interaction

1. **Wake** — Vosk detects "Proxy". `WAKE` event published. State: IDLE → WAKE_DETECTED.
2. **Wake handling** — Session activated, wake sound played (greeting on first wake, casual on subsequent). `READY` event published. State: WAKE_DETECTED → LISTENING. Turn timer starts.
3. **Listening** — Audio forwarded to Deepgram. Partials arrive and reset the listening timeout. User finishes speaking, Deepgram sends finalized segments, then UtteranceEnd. `USER_FINAL` published. State: LISTENING → THINKING.
4. **Thinking** — Transcript sent to Copilot. Copilot may emit thoughts ("Reviewing technical debt") which are spoken via TTS. Tool calls are logged. First response partial arrives. State: THINKING → SPEAKING.
5. **Speaking** — Copilot streams text. Chunking layer splits at sentence boundaries. Each chunk is synthesized by ElevenLabs and played back. State remains SPEAKING.
6. **Completion** — `ASSISTANT_FINAL` arrives. Remaining TTS buffer flushed. Turn timing logged. State: SPEAKING → IDLE. Ready for next wake word.

## Interruption

Saying "stop" during THINKING or SPEAKING:
1. Vosk detects the stopword. `INTERRUPT` event published.
2. State: THINKING/SPEAKING → LISTENING.
3. Copilot turn cancelled, TTS playback stopped, TTS queue drained.
4. User can speak their next prompt immediately.

## Cancellation

Saying "never mind" or "quit" during LISTENING:
1. STT final callback detects the cancel phrase.
2. `CANCEL` event published. State: LISTENING → IDLE.

## Session reset

Saying "new session" during LISTENING:
1. STT final callback detects the command.
2. Active session cancelled, new session created and bootstrapped.
3. Conversation context is reset.

## Shutdown

On termination: wake engine stopped, Copilot hard-stopped, TTS cancelled, playback cancelled, `STOP` event published, orchestrator stopped.
