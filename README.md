<div align="center">

# Proxy

### Give your coding agent a voice.

Wake word → Speech-to-text → Copilot → Text-to-speech → Speaker

*All streaming. All low-latency. Fully hands-free.*

---

[Getting Started](#getting-started) · [How It Works](#how-it-works) · [Features](#features) · [Configuration](#configuration) · [Contributing](#contributing)

</div>

---

## Why Proxy?

You already have a coding agent. It's good at what it does. But every time you want to ask it something, you stop coding, switch context, type a prompt, wait, read the response, and switch back.

Proxy sits between you and your agent — that's it. It's not a new AI, not a framework, not a platform. It's a voice layer that proxies your speech to the agent and speaks the response back. Your agent does the thinking. Proxy just gives it a voice.

---

## What does it look like?

```
You:     "Proxy, what's the technical debt in the autograder repo?"
Proxy:   *acknowledgment sound*
Proxy:   "Reviewing technical debt..."           ← spoken thought
         Reading 8 files...                      ← terminal log
Proxy:   "I found three main areas of            ← streamed response
          technical debt. First, the config
          system still uses..."
You:     "Stop."                                 ← interrupt mid-speech
Proxy:   *silence*
         *listening for your next prompt*
```

No browser tabs. No copy-paste. No keyboard. Just your voice and your code.

---

## Features

**Wake word activation** — Say "Proxy" to start. Local Vosk model, no cloud dependency for wake detection.

**Streaming responses** — Hear Copilot's answer while it's still generating. Sentence-boundary chunking feeds ElevenLabs TTS in real-time.

**Thought narration** — When Copilot is thinking ("Reviewing technical debt", "Exploring codebase"), Proxy speaks it so you know what's happening.

**Voice interruption** — Say "stop" anytime during a response to cancel and take back control. Instantly.

**Persistent sessions** — One Copilot session lives for the entire process. Full conversational context across every interaction.

**Anti self-listening** — Two-layer protection (speech gate + echo filter) prevents Proxy from transcribing its own voice.

**Contextual wake sounds** — First interaction gets a greeting. Subsequent ones get a casual callup.

**Fully configurable** — 40+ environment variables for tuning every aspect: voice, latency, wake sensitivity, STT model, and more.

---

## Getting Started

- Python 3.11+, [PortAudio](http://www.portaudio.com/), [GitHub Copilot CLI](https://docs.github.com/en/copilot/github-copilot-in-the-cli) installed and authenticated
- API keys for [Deepgram](https://console.deepgram.com) (STT) and [ElevenLabs](https://elevenlabs.io/api) (TTS)
- A [Vosk model](https://alphacephei.com/vosk/models) for wake word detection

```bash
git clone https://github.com/ArthurCRodrigues/proxy.git
cd proxy
pip install -e ".[dev]"
proxy init                     # guided setup: downloads model, configures API keys
proxy                          # say "Proxy" and start talking
```

### Run at startup (Linux)

Make sure your `.env` file is configured with your API keys first, then:

```bash
proxy setup
```

This installs a systemd user service that launches Proxy on login. Useful commands after installing:

```bash
systemctl --user status proxy     # check if it's running
journalctl --user -u proxy -f     # follow the logs
systemctl --user stop proxy       # stop it
systemctl --user disable proxy    # remove from startup
```

---

## How It Works

Proxy sits between your microphone and your coding agent. Audio flows through five components in sequence:

1. **Vosk** (local) listens for the wake word — no cloud calls, no latency.
2. **Deepgram** transcribes your speech in real-time over a persistent websocket.
3. **Copilot** receives the transcript via ACP and streams back a response.
4. **ElevenLabs** converts each sentence to speech as it arrives.
5. **Speaker** plays the audio while Copilot is still generating.

Saying **"stop"** at any point during steps 3–5 cancels everything and returns control to you.

### States

Proxy is a state machine with five states. Each interaction follows the same path:

| State | What's happening | How it ends |
|---|---|---|
| **IDLE** | Waiting for wake word. Nothing else running. | You say "Proxy" → LISTENING |
| **LISTENING** | Deepgram is transcribing your voice. | You finish speaking → THINKING. You say "never mind" → IDLE. Silence for 10s → IDLE. |
| **THINKING** | Your prompt was sent to Copilot. Waiting for a response. Thoughts are spoken aloud. | First response chunk arrives → SPEAKING. You say "stop" → LISTENING. |
| **SPEAKING** | Copilot's response is streaming through TTS and playing back. | Response finishes → IDLE. You say "stop" → LISTENING. |
| **STOPPED** | Shutting down. Terminal state. | — |

---

## Configuration

All settings are environment variables. See [`.env.example`](.env.example) for the full list.

### Key settings

| Variable | Default | What it does |
|---|---|---|
| `PROXY_WAKE_PHRASE` | `proxy` | The wake word |
| `PROXY_WAKE_ALIASES` | `proxy,roxy,rocky` | Alternative wake word spellings for better recognition |
| `PROXY_STOPWORD_ALIASES` | `stop,shut up` | Phrases that interrupt the current response |
| `PROXY_LISTENING_TIMEOUT_MS` | `10000` | How long to wait for speech before returning to IDLE |
| `PROXY_DEEPGRAM_UTTERANCE_END_MS` | `3500` | Silence duration before Deepgram finalizes your speech |
| `PROXY_ELEVENLABS_VOICE_ID` | — | Your ElevenLabs voice (required) |
| `PROXY_ELEVENLABS_SPEED` | `0.95` | TTS speech speed |
| `PROXY_COPILOT_COMMAND` | `copilot` | CLI command to invoke Copilot |
| `PROXY_LOG_LEVEL` | `INFO` | Logging level |
| `PROXY_LOG_DEBUG_MODULES` | — | Comma-separated modules for DEBUG logging (e.g. `proxy.stt.deepgram`) |

---

### Custom instructions

Place an `instructions.md` file in the project root to give your agent custom context. This file is sent as system instructions when the session starts. Use it to tell the agent about your project, preferred response style, or domain-specific knowledge.

If no file is found, Proxy uses built-in defaults that tell the agent to respond in plain conversational language suitable for voice.

### Wake sounds

Proxy plays a short audio clip when the wake word is detected. You need to provide your own WAV files:

- `assets/greetings/` — played on the first wake of a session (e.g. "Hello!", "Hey there!")
- `assets/wake/` — played on subsequent wakes (e.g. "Yes?", "Hm?")
- `assets/yes.wav` — fallback if the directories above are empty

Place one or more `.wav` files (PCM 16-bit) in each directory. Proxy picks one at random each time.

---

## What's Next

Proxy currently works with GitHub Copilot. Here's where it's headed:

- **Claude Code support** — first priority. Proxy should work with the most popular agent runtimes, not just one.
- **Agent-agnostic protocol** — a simple bridge interface so any coding agent can plug in.
- **ElevenLabs WebSocket streaming** — true real-time TTS for lower latency.
- **Alternative STT/TTS providers** — Whisper, local TTS, Azure, Google.
- **Non-English language support** — wake word models and STT/TTS configs for other languages.

See the full [roadmap](ROADMAP.md) for details.

---

## Contributing

Proxy is built to be extended. Some areas where contributions would be especially valuable:

**Agent backends** — Proxy currently works with GitHub Copilot. Adding support for Claude Code, Aider, Continue, or other coding agents would make it useful to a much wider audience.

**STT/TTS providers** — Alternative speech engines (Whisper, Azure, Google, local TTS) for different cost/latency/privacy tradeoffs.

**Language support** — Wake word models and STT configs for non-English languages.

**Latency optimization** — Every millisecond matters in voice UX. Profiling, benchmarking, and optimization PRs are welcome.

**Testing** — Integration tests, edge case coverage, CI pipeline.

---

## License

MIT

---

<div align="center">

**Proxy** — because your coding agent deserves a voice.

</div>
