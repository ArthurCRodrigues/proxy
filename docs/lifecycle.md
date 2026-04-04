# Lifecycle & Wiring

This document describes how Proxy boots up, processes a complete voice interaction, and shuts down. It traces the flow through every component to show how they connect.

## Startup sequence

`main.py` is the entry point. The `_run()` coroutine wires everything together:

1. **Configuration** — `Settings.from_env()` loads the `.env` file and reads all `PROXY_*` environment variables into a frozen dataclass.

2. **Infrastructure** — Creates the `EventBus`, `PlaybackEngine`, and `AudioIO` (microphone capture).

3. **STT** — Creates the `DeepgramSTTAdapter` and registers two callbacks: `_on_partial` and `_on_final`. These callbacks gate transcripts through the speech gate and echo filter before publishing events to the bus.

4. **TTS** — Creates the `ElevenLabsTTSAdapter` and starts a dedicated TTS worker task. This worker consumes ordered text commands, manages the realtime stream lifecycle, and coordinates playback.

5. **Copilot** — Creates the `CopilotBridge` with assistant partial/final callbacks that feed the realtime TTS command queue. Creates a `SessionPool` wrapping the bridge.

6. **Orchestrator** — Creates the `Orchestrator` with the event bus, a wake callback, and the copilot bridge. Sets the listening timeout. Starts `orchestrator.run()` as a background task.

7. **Session prewarm** — `session_pool.ensure_active()` creates the first Copilot ACP session in the background. This session is bootstrapped with system instructions so it's ready when the user speaks.

8. **Wake engine** — Creates and starts the `WakeVadEngine`, which opens the microphone stream, loads the Vosk model, and begins the audio processing loop.

Proxy is now in `IDLE` state, listening for the wake word.

## A complete interaction

Here's what happens when the user says "Proxy, what's the weather?":

### 1. Wake detection

The `WakeVadEngine` processes audio chunks in a loop. The Vosk recognizer detects "proxy" in the audio. The engine publishes a `WAKE` event to the bus.

### 2. Wake handling

The orchestrator receives `WAKE`. The state machine transitions `IDLE` → `WAKE_DETECTED`. The orchestrator calls the `on_wake` callback:

- `session_pool.activate()` — activates the pre-warmed session.
- A random wake sound is loaded and played. The speech gate is blocked and "yes" is recorded in the echo filter.

The orchestrator then publishes a `READY` event.

### 3. Listening

The orchestrator receives `READY`. The state machine transitions `WAKE_DETECTED` → `LISTENING`. The listening timeout is armed (10 seconds).

Audio chunks are now forwarded to Deepgram (the STT gate allows it because the state is `LISTENING`). The user says "what's the weather?"

Deepgram sends partial transcripts: "what's", "what's the", "what's the weather". Each triggers a `USER_PARTIAL` event that resets the listening timeout.

### 4. End of speech

The VAD detects 700ms of silence after the user stops speaking. It calls `stt.end_utterance()`, which sends a `Finalize` command to Deepgram.

Deepgram responds with a final transcript: "What's the weather?" The `_on_final` callback in `main.py` checks it's not a cancel command, then publishes a `USER_FINAL` event.

### 5. Thinking

The orchestrator receives `USER_FINAL`. The state machine transitions `LISTENING` → `THINKING`. The listening timeout is cancelled.

The orchestrator calls `copilot.send_user_turn("What's the weather?", turn_id=...)`. The bridge wraps the text with bootstrap instructions (if first turn) and sends it to the active Copilot session via `session/prompt`.

### 6. Streaming response

Copilot starts generating. The ACP process sends `session/update` notifications with text chunks. The bridge accumulates them and calls `_on_assistant_partial` for each chunk, which also publishes `ASSISTANT_PARTIAL` events.

The first `ASSISTANT_PARTIAL` event transitions the state machine `THINKING` → `SPEAKING`.

Meanwhile, the `_on_assistant_partial` callback enqueues each partial into the TTS command queue. The TTS worker starts the ElevenLabs WebSocket stream if needed, pushes each text delta in order, and playback consumes audio chunks as they arrive.

### 7. Completion

When Copilot finishes, the `session/prompt` future resolves. The bridge joins all accumulated text parts and calls `_on_assistant_final`, which publishes `ASSISTANT_FINAL`.

The `_on_assistant_final` callback enqueues a stream-finalize command so the adapter flushes trailing audio before playback ends.

The orchestrator receives `ASSISTANT_FINAL`. The state machine transitions `SPEAKING` → `IDLE`. Context is cleared.

Proxy is back in `IDLE`, listening for the next wake word. The Copilot session remains active — the next interaction will continue the same conversation.

## Session reset

If the user says "start new session" (or "new session", "reset session", "fresh session"), the `_on_final` callback detects it and calls `_reset_copilot_session()`. This:

1. Cancels any in-flight prompt.
2. Creates a fresh Copilot session.
3. The new session will be bootstrapped on its first use.

The state machine is not involved — this happens at the application layer.

## Cancellation

If the user says a cancel phrase (e.g. "never mind", "quit"), the `_on_final` callback interrupts active TTS immediately and publishes a `CANCEL` event. The state machine transitions back to `IDLE` from `LISTENING`, `THINKING`, or `SPEAKING`.

## Shutdown

On `KeyboardInterrupt` or other termination:

1. The wake engine is stopped (cancels the audio loop, closes the microphone).
2. The Copilot bridge is hard-stopped (cancels all tasks, terminates the ACP process).
3. The TTS worker is stopped.
4. The TTS adapter stream is cancelled.
5. Playback is cancelled.
6. A `STOP` event is published, transitioning the state machine to `STOPPED`.
7. The orchestrator runner task is cancelled.
