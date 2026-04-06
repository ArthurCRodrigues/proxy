# Proxy Open-Source Launch Roadmap

Date: 2026-04-06

## Vision

Proxy is a voice layer for coding agents. Not a personal assistant, not a general-purpose voice AI — just the piece that gives your existing coding agent a voice. Wake word in, spoken answer out, with low latency.

The goal is to ship a tool that works perfectly with one agent (Copilot) and is trivially extensible to others (Claude Code, Aider, Continue, custom agents).

---

## Priority 1: Agent Abstraction

**Problem:** Proxy is hardwired to Copilot ACP. Every coding agent has a different interface — Copilot uses ACP/JSON-RPC, Claude Code uses stdin/stdout, Aider uses a CLI, others use HTTP APIs. If Proxy only works with Copilot, adoption is limited to Copilot users.

**Solution:** Define a `CodingAgentBridge` protocol that any agent can implement.

### Interface

```python
class CodingAgentBridge(Protocol):
    async def start(self) -> None
    async def send_prompt(self, text: str, turn_id: str | None = None) -> None
    async def cancel(self) -> None
    async def stop(self) -> None

    # Callbacks set by the caller
    on_partial: Callable[[str], None] | None
    on_final: Callable[[str], None] | None
```

That's it. The agent receives text prompts and streams back text responses. Proxy handles everything else (wake, STT, TTS, state machine, anti self-listening).

### Changes

| File | Change |
|---|---|
| `proxy/agents/protocol.py` | New file: `CodingAgentBridge` protocol definition |
| `proxy/agents/copilot.py` | Move current `CopilotBridge` here, implement the protocol |
| `proxy/orchestrator/engine.py` | Type hint the bridge as `CodingAgentBridge` instead of `CopilotBridge` |
| `proxy/main.py` | Agent selection via `PROXY_AGENT` config (default: `copilot`) |
| `proxy/config.py` | Add `agent: str` field |

### Session management

Session lifecycle (bootstrap, reset, "new session" command) is agent-specific. The protocol doesn't prescribe it. Each agent implementation handles its own session semantics internally. The `SessionPool` stays inside the Copilot agent implementation.

---

## Priority 2: Interruption (Barge-In)

**Problem:** Once Proxy starts speaking a long answer, the user has no way to stop it. They have to wait for the full response to finish before they can speak again.

**Solution:** Saying the wake word while Proxy is in THINKING or SPEAKING state cancels the current response and returns to LISTENING.

### State machine changes

Add a transition: `SPEAKING` + `WAKE` → `LISTENING` (interrupt path).

When this fires:
1. Cancel the active Copilot prompt task.
2. Cancel TTS playback immediately.
3. Flush the TTS queue.
4. Play a short acknowledgment sound.
5. Transition to LISTENING — the user can speak their next prompt.

### Wake engine changes

Currently `wake_enabled` returns True only in IDLE. Change it to also return True in THINKING and SPEAKING. The wake gating logic (rearm guard, cooldown) stays the same.

### Anti self-listening consideration

The wake word detector (Vosk, local) is separate from the STT pipeline (Deepgram, cloud). Vosk processes all audio regardless of state. The speech gate and echo filter only affect Deepgram. So wake detection during SPEAKING already works — it just needs to be allowed by the state gate.

---

## Priority 3: Setup CLI (`proxy init`)

**Problem:** First-time setup requires manually installing 5 external dependencies, downloading a Vosk model, creating a `.env` file, and filling in 3 API keys. Most users will give up.

**Solution:** A guided `proxy init` command that walks through everything.

### Flow

```
$ proxy init

Proxy Setup
============

[1/5] Checking PortAudio... ✓ found
[2/5] Checking Vosk model...
      Model not found at assets/models/vosk-model-small-en-us-0.15
      Download now? [Y/n] y
      Downloading... done

[3/5] Deepgram API key (for speech-to-text):
      Get one at https://console.deepgram.com
      Key: dg_xxxxx ✓ valid

[4/5] ElevenLabs API key (for text-to-speech):
      Get one at https://elevenlabs.io/api
      Key: el_xxxxx ✓ valid
      Voice ID: xxxxx ✓ valid

[5/5] Copilot CLI...
      ✓ copilot command found and authenticated

Writing .env... done
Ready! Run `proxy` to start.
```

### Validation

Each step validates the dependency actually works:
- PortAudio: try importing `sounddevice`
- Vosk: check model directory exists and contains expected files
- Deepgram: make a test websocket connection with the key
- ElevenLabs: make a test API call to validate key + voice ID
- Copilot: run `copilot --version` or equivalent

### Changes

| File | Change |
|---|---|
| `proxy/cli.py` | New file: `init` subcommand with guided setup |
| `proxy/main.py` | Move `cli()` to `proxy/cli.py`, add subcommand routing |

---

## Priority 4: Packaging & Distribution

**Problem:** No `pyproject.toml`. Can't `pip install`. No entry point registered.

**Solution:** Standard Python packaging so users can install with one command.

### Target

```bash
pip install proxy-voice
proxy init
proxy
```

### Changes

| File | Change |
|---|---|
| `pyproject.toml` | New: project metadata, dependencies, `[project.scripts]` entry point |
| `proxy/cli.py` | Entry point: `proxy` command with `run` (default) and `init` subcommands |

### Dependencies to declare

- `websockets` (Deepgram + ElevenLabs)
- `vosk` (wake word)
- `sounddevice` (audio I/O)
- `elevenlabs` (TTS SDK)
- `numpy` (sounddevice dependency)

Optional/dev:
- `pytest`

---

## Priority 5: Latency Tracing

**Problem:** Voice latency is the product. Users need to know where time is spent. Currently there's no instrumentation.

**Solution:** Log a timing breakdown for every turn.

### What to measure

| Metric | Start | End |
|---|---|---|
| Wake-to-listening | WAKE event | READY event |
| Listening duration | READY event | USER_FINAL event |
| STT finalization | Last speech → UtteranceEnd | USER_FINAL event |
| Copilot TTFB | USER_FINAL sent | First ASSISTANT_PARTIAL |
| Copilot total | USER_FINAL sent | ASSISTANT_FINAL |
| TTS TTFB | First chunk sent to TTS | First audio played |
| Total turn | WAKE event | Last audio played |

### Output

Log a single summary line at the end of each turn:

```
TURN_TIMING wake=85ms listen=3200ms copilot_ttfb=1100ms copilot_total=4500ms tts_ttfb=320ms total=8200ms
```

### Changes

| File | Change |
|---|---|
| `proxy/observability/timing.py` | New: `TurnTimer` class that tracks timestamps per phase |
| `proxy/main.py` | Create a `TurnTimer` per wake cycle, stamp it at each phase boundary |

---

## Priority 6: Test & Documentation Cleanup

**Problem:** Some tests reference deleted code. Docs describe a codebase state that no longer matches main. The ElevenLabs adapter tests test the old REST interface.

### Tests

- Fix `test_elevenlabs_adapter.py` to match current REST adapter on main
- Remove `test_tts_chunking.py` if chunking was removed, or keep if it's back on main
- Add integration-style test: mock Deepgram + ElevenLabs websockets, run a full wake→listen→think→speak cycle
- Verify all tests pass with `pytest -q`

### Docs

- Sync README with actual current code
- Sync `docs/` files with actual current architecture
- Add `docs/adding-an-agent.md` — guide for implementing a new agent bridge
- Add `CONTRIBUTING.md` — how to set up dev environment, run tests, submit PRs

---

## Execution Order

```
1. Agent abstraction     ← unlocks community contributions
2. Interruption          ← essential UX for a voice product
3. Packaging             ← needed before any public release
4. Setup CLI             ← first-run experience
5. Latency tracing       ← operational visibility
6. Test & doc cleanup    ← polish for launch
```

Items 1-4 are launch blockers. Items 5-6 are launch quality.

---

## Out of Scope for Launch

- WebSocket TTS (ElevenLabs streaming) — attempted and reverted, revisit post-launch
- Stopword/barge-in via separate phrase — wake word interrupt covers the core need
- Speech arbitration / tool narration — nice-to-have, not launch-critical
- Multiple simultaneous agents — one agent at a time is fine
- GUI / web interface — CLI-first
