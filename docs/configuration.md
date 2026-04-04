# Configuration Reference

All configuration is done through environment variables. Proxy reads a `.env` file from the working directory at startup (values don't override existing environment variables). Copy `.env.example` to `.env` and fill in the required values.

## API credentials

| Variable | Required | Description |
|---|---|---|
| `DEEPGRAM_API_KEY` | Yes | Deepgram API key for speech-to-text |
| `ELEVENLABS_API_KEY` | Yes | ElevenLabs API key for text-to-speech |
| `ELEVENLABS_VOICE_ID` | Yes | ElevenLabs voice to use for synthesis |

These three variables use unprefixed names because they're standard across tools.

## Runtime

| Variable | Default | Description |
|---|---|---|
| `PROXY_LOG_LEVEL` | `INFO` | Python logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `PROXY_QUEUE_MAXSIZE` | `256` | Maximum events in the event bus queue |

## Audio I/O

| Variable | Default | Description |
|---|---|---|
| `PROXY_AUDIO_SAMPLE_RATE` | `16000` | Microphone capture sample rate (Hz) |
| `PROXY_AUDIO_CHANNELS` | `1` | Capture channels (1 = mono) |
| `PROXY_AUDIO_CHUNK_MS` | `20` | Duration of each audio chunk (ms) |
| `PROXY_AUDIO_INPUT_QUEUE_MAXSIZE` | `128` | Max buffered audio chunks before dropping oldest |
| `PROXY_AUDIO_INPUT_DEVICE` | (system default) | Input device index or name substring |
| `PROXY_YES_ASSET_PATH` | `assets/yes.wav` | Fallback wake acknowledgment sound |
| `PROXY_WAKE_SOUNDS_DIR` | `assets/wake` | Directory of wake acknowledgment WAV files |

## Wake word & VAD

| Variable | Default | Description |
|---|---|---|
| `PROXY_WAKE_PHRASE` | `proxy` | Primary wake phrase |
| `PROXY_WAKE_ALIASES` | `proxy,roxy, rocky` | Comma-separated wake phrase variants (catches misrecognitions) |
| `PROXY_VOSK_MODEL_PATH` | `assets/models/vosk-model-small-en-us-0.15` | Path to Vosk speech model directory |
| `PROXY_VAD_START_RMS` | `600.0` | Minimum RMS to detect speech start |
| `PROXY_VAD_END_RMS` | `350.0` | Maximum RMS to count as silence |
| `PROXY_VAD_END_SILENCE_MS` | `700` | Silence duration to trigger end-of-speech (ms) |
| `PROXY_WAKE_DEBUG_TRANSCRIPTS` | `0` | Log all Vosk recognition results |
| `PROXY_WAKE_DEBUG_RMS` | `0` | Log RMS value of every audio chunk |
| `PROXY_WAKE_RETRIGGER_COOLDOWN_MS` | `1500` | Minimum interval between wake events (ms) |
| `PROXY_WAKE_REARM_GUARD_MS` | `1200` | Delay before re-enabling wake after returning to IDLE (ms) |
| `PROXY_WAKE_MATCH_PARTIAL` | `0` | Also check Vosk partial results for wake phrase (increases false positives) |

## Deepgram STT

| Variable | Default | Description |
|---|---|---|
| `PROXY_DEEPGRAM_MODEL` | `nova-3` | Deepgram model name |
| `PROXY_DEEPGRAM_LANGUAGE` | `en-US` | Recognition language |
| `PROXY_DEEPGRAM_ENDPOINTING_ENABLED` | `1` | Enable Deepgram's built-in endpointing |
| `PROXY_DEEPGRAM_ENDPOINTING_MS` | `700` | Deepgram endpointing silence threshold (ms) |
| `PROXY_DEEPGRAM_UTTERANCE_END_MS` | `3500` | Deepgram utterance end timeout (ms) |
| `PROXY_DEEPGRAM_PUNCTUATE` | `1` | Enable automatic punctuation |
| `PROXY_DEEPGRAM_SMART_FORMAT` | `1` | Enable smart formatting (numbers, dates, etc.) |
| `PROXY_DEEPGRAM_KEYTERMS` | (empty) | Comma-separated terms to boost in recognition |
| `PROXY_DEEPGRAM_INTERIM_RESULTS` | `1` | Enable interim (partial) results |
| `PROXY_DEEPGRAM_RECONNECT_MAX_ATTEMPTS` | `3` | Max websocket reconnection attempts |
| `PROXY_DEEPGRAM_RECONNECT_BASE_DELAY_MS` | `200` | Base delay between reconnection attempts (ms) |

## Speech turn controls

| Variable | Default | Description |
|---|---|---|
| `PROXY_STT_GATE_ENABLED` | `1` | Enable the speech gate (time-based STT blocking after TTS) |
| `PROXY_STT_GATE_HOLD_MS` | `900` | Speech gate hold duration (ms) |
| `PROXY_STT_DEECHO_ENABLED` | `1` | Enable the echo filter (similarity-based STT rejection) |
| `PROXY_STT_DEECHO_SIMILARITY_THRESHOLD` | `0.78` | Minimum SequenceMatcher ratio to classify as echo |
| `PROXY_LISTENING_TIMEOUT_MS` | `10000` | Inactivity timeout while listening (ms). `0` disables. |
| `PROXY_CANCEL_COMMANDS` | `nevermind,never mind,quit` | Comma-separated cancel phrases |

## Copilot

| Variable | Default | Description |
|---|---|---|
| `PROXY_COPILOT_COMMAND` | `copilot` | CLI command to invoke Copilot |
| `PROXY_COPILOT_MODEL` | (empty) | Model override (passed as `--model`). Empty uses Copilot's default. |
| `PROXY_COPILOT_ALLOW_ALL` | `1` | Auto-approve all Copilot permission requests |
| `PROXY_COPILOT_INSTRUCTIONS_PATH` | `<project_root>/copilot-instructions.md` | Path to bootstrap instructions file. Falls back to built-in voice instructions if not found. |

## ElevenLabs TTS

| Variable | Default | Description |
|---|---|---|
| `PROXY_ELEVENLABS_MODEL_ID` | `eleven_multilingual_v2` | ElevenLabs model |
| `PROXY_ELEVENLABS_OUTPUT_FORMAT` | `pcm_22050` | Primary output format |
| `PROXY_ELEVENLABS_LATENCY_MODE` | `optimistic` | ElevenLabs WebSocket latency mode |
| `PROXY_ELEVENLABS_STABILITY` | `0.45` | Voice stability (0.0–1.0) |
| `PROXY_ELEVENLABS_SIMILARITY_BOOST` | `0.85` | Voice similarity boost (0.0–1.0) |
| `PROXY_ELEVENLABS_STYLE` | `0.65` | Style exaggeration (0.0–1.0) |
| `PROXY_ELEVENLABS_SPEED` | `0.95` | Speech speed multiplier |
| `PROXY_ELEVENLABS_USE_SPEAKER_BOOST` | `1` | Enable speaker boost |

## TTS streaming

| Variable | Default | Description |
|---|---|---|
| `PROXY_TTS_TEXT_QUEUE_MAXSIZE` | `128` | Maximum buffered outbound text updates before backpressure handling |
| `PROXY_TTS_AUDIO_QUEUE_MAXSIZE` | `256` | Maximum buffered inbound audio chunks for playback |
