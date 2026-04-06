# Configuration Reference

All configuration is through environment variables. Proxy reads a `.env` file from the working directory at startup. See `.env.example` for the recommended settings.

## Required

| Variable | Description |
|---|---|
| `DEEPGRAM_API_KEY` | Deepgram API key for speech-to-text |
| `ELEVENLABS_API_KEY` | ElevenLabs API key for text-to-speech |
| `ELEVENLABS_VOICE_ID` | ElevenLabs voice to use |

## Wake word & stopword

| Variable | Default | Description |
|---|---|---|
| `PROXY_WAKE_PHRASE` | `proxy` | Primary wake phrase |
| `PROXY_WAKE_ALIASES` | `proxy,roxy,rocky` | Comma-separated wake phrase variants |
| `PROXY_STOPWORD_ALIASES` | `stop,shut up` | Phrases that interrupt during THINKING/SPEAKING |

## Deepgram STT

| Variable | Default | Description |
|---|---|---|
| `PROXY_DEEPGRAM_MODEL` | `nova-3` | Recognition model |
| `PROXY_DEEPGRAM_LANGUAGE` | `en-US` | Language |
| `PROXY_DEEPGRAM_UTTERANCE_END_MS` | `3500` | Silence before speech is finalized (ms) |
| `PROXY_DEEPGRAM_KEYTERMS` | (empty) | Domain-specific terms to boost recognition |

## ElevenLabs TTS

| Variable | Default | Description |
|---|---|---|
| `PROXY_ELEVENLABS_MODEL_ID` | `eleven_multilingual_v2` | TTS model |
| `PROXY_ELEVENLABS_SPEED` | `0.95` | Speech speed multiplier |

## Copilot

| Variable | Default | Description |
|---|---|---|
| `PROXY_COPILOT_COMMAND` | `copilot` | CLI command to invoke Copilot |
| `PROXY_COPILOT_MODEL` | (empty) | Model override (passed as `--model`) |

## Behavior

| Variable | Default | Description |
|---|---|---|
| `PROXY_LISTENING_TIMEOUT_MS` | `10000` | Inactivity timeout while listening (ms). `0` disables. |

## Logging

| Variable | Default | Description |
|---|---|---|
| `PROXY_LOG_LEVEL` | `INFO` | Python logging level |
| `PROXY_LOG_DEBUG_MODULES` | (empty) | Comma-separated modules for DEBUG logging (e.g. `proxy.stt.deepgram`) |

## Advanced (not in .env.example)

These have sensible defaults and rarely need changing. Set them as environment variables if needed.

| Variable | Default | Description |
|---|---|---|
| `PROXY_ELEVENLABS_OUTPUT_FORMAT` | `pcm_22050` | TTS output format |
| `PROXY_ELEVENLABS_FALLBACK_OUTPUT_FORMATS` | `wav_22050` | Fallback formats on 403 |
| `PROXY_ELEVENLABS_STABILITY` | `0.45` | Voice stability |
| `PROXY_ELEVENLABS_SIMILARITY_BOOST` | `0.85` | Voice similarity |
| `PROXY_ELEVENLABS_STYLE` | `0.25` | Style exaggeration |
| `PROXY_ELEVENLABS_USE_SPEAKER_BOOST` | `1` | Speaker boost |
| `PROXY_AUDIO_SAMPLE_RATE` | `16000` | Capture sample rate (Hz) |
| `PROXY_AUDIO_INPUT_DEVICE` | (default) | Input device index or name |
| `PROXY_QUEUE_MAXSIZE` | `256` | Event bus queue size |
| `PROXY_WAKE_RETRIGGER_COOLDOWN_MS` | `1500` | Min interval between wake events |
| `PROXY_WAKE_REARM_GUARD_MS` | `1200` | Delay before re-enabling wake after IDLE |
| `PROXY_STOPWORD_COOLDOWN_MS` | `1500` | Min interval between stopword events |
| `PROXY_STT_GATE_HOLD_MS` | `900` | Speech gate hold after TTS (ms) |
| `PROXY_STT_DEECHO_SIMILARITY_THRESHOLD` | `0.78` | Echo filter fuzzy match threshold |
| `PROXY_CANCEL_COMMANDS` | `nevermind,never mind,quit` | Cancel phrases during LISTENING |
| `PROXY_TTS_SPEAK_PARTIALS` | `1` | Stream TTS from partials |
| `PROXY_TTS_PARTIAL_MIN_CHARS` | `12` | Min chars before emitting a TTS chunk |
| `PROXY_TTS_PARTIAL_FORCE_FLUSH_CHARS` | `72` | Force-emit without boundary |
| `PROXY_INSTRUCTIONS_PATH` | `instructions.md` | Bootstrap instructions file |
