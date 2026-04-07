# Roadmap

Proxy gives coding agents a voice. This roadmap outlines what's next.

---

## Agent support

Proxy currently works with GitHub Copilot via ACP. The architecture should support any coding agent.

- **Agent-agnostic protocol** — Define a simple bridge interface (`send_prompt` → `on_partial`/`on_final`) that any agent can implement. Ship Copilot as the default, let the community add others.
- **Claude Code, Aider, Continue** — First-party or community-contributed agent backends for the most popular coding assistants.
- **MCP server integration** — Pass MCP server configs to agents that support them, enabling tool use (Spotify, browser, deployment, databases) through voice.

## Voice quality

Every millisecond of latency matters in a voice product.

- **ElevenLabs WebSocket streaming** — Replace per-sentence REST calls with a persistent WebSocket connection. Text streams in, audio streams back. True real-time synthesis.
- **Alternative TTS providers** — Local TTS (Piper, Coqui) for privacy and zero-cost operation. Azure and Google for enterprise deployments.
- **Alternative STT providers** — Whisper (local or API) for offline use or different accuracy/cost tradeoffs. Azure Speech Services for enterprise.

## Interaction model

Voice UX goes beyond just speaking and listening.

- **Stopword refinement** — Configurable interrupt behavior, optional confirmation sounds, cooldown tuning to prevent false triggers from TTS output.
- **Voice status check** — Say "what's happening?" during long Copilot silences to hear a spoken summary of recent activity (files read, tools used, current thought) without interrupting the ongoing work.
- **Voice commands** — Built-in commands beyond prompts: "read that again", "save that to a file", "run that command", "start new session."
- **Voice logs command** — After wake word detection, saying "show logs" or "logs" opens a terminal window streaming Proxy process logs for live debugging.
- **Multi-turn terminal UI** — A clean terminal display showing conversation history, current state, and Copilot activity (tool calls, thoughts) alongside the voice interaction.

## Accessibility and reach

Proxy should work for everyone, everywhere.

- **Non-English language support** — Wake word models, STT configs, and TTS voices for languages beyond English.
- **Cross-platform packaging** — Tested and documented installation for macOS, Linux, and Windows.
- **Docker image** — A container with all dependencies pre-installed for zero-setup trial runs.

## Developer experience

Making it easy to extend and contribute.

- **Plugin system** — A clean interface for registering custom STT, TTS, and agent providers without modifying core code.
- **Latency benchmarking** — Extend the existing Copilot latency benchmark to cover the full pipeline: wake detection, STT, agent TTFB, TTS, and time-to-first-audio.
