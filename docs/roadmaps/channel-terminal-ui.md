# Channel — Live Terminal UI & Text Handoff

## Problem

Voice is great for conversation but terrible for URLs, code snippets, stack traces, and structured content. When the user wants to share a link with the agent or the agent wants to show a code example, voice breaks down. Additionally, during long Copilot tool-use silences, the user has no visibility into what's happening unless they're watching raw logs.

## Vision

A live terminal UI that runs alongside the voice session. It shows everything happening in real-time and provides a text input for bidirectional content sharing between the user and the agent.

```
┌─ Proxy ──────────────────────────────────────────────┐
│                                                       │
│  [14:44:27] You: "What's the technical debt in the   │
│             autograder repo?"                          │
│  [14:44:36] Proxy: "On it, I'll do a quick codebase  │
│             pass..."                                   │
│  [14:44:38] 🔧 Viewing /autograder                    │
│  [14:44:38] 🔧 Viewing README.md                      │
│  [14:44:38] 🔧 Viewing pyproject.toml                 │
│  [14:44:49] 🔧 Finding files matching proxy/**/*.py   │
│  [14:44:49] 🔧 Viewing main.py                        │
│  [14:44:49] 🔧 Viewing config.py (+ 6 more)           │
│  [14:59:30] Proxy: "I found three main areas of       │
│             technical debt. First..."                  │
│                                                       │
│  [channel] https://testcontainers.com/docs            │
│                                                       │
├───────────────────────────────────────────────────────┤
│ > paste a URL, code, or message here                  │
└───────────────────────────────────────────────────────┘
```

## Use cases

### User → Agent (text handoff)

The user pastes a URL, code snippet, or any text into the channel input. When they speak their next voice prompt, the channel content is automatically attached.

Example flow:
1. User pastes `https://testcontainers.com/guides/getting-started` into the channel
2. User says: "Proxy, I want you to use the test containers library in this Java project. I placed a URL for the docs in the channel, check it out."
3. The bridge prepends the channel content to the Copilot prompt
4. Channel is cleared after reading

### Agent → User (content sharing)

When Copilot's response contains code blocks, URLs, or structured content that doesn't translate well to speech, the bridge writes it to the channel and the TTS says something like "I've put that in the channel."

Example flow:
1. User says: "Add structured logging to the project"
2. Copilot generates code and an explanation
3. The explanation is spoken via TTS
4. The code example appears in the channel
5. TTS says: "I've written an example in the channel so you can see how it looks."

### Live activity feed

The channel displays all Copilot events in real-time:
- User prompts (from STT finals)
- Agent thoughts ("Reviewing technical debt...")
- Tool calls ("Viewing main.py", "Finding files matching *.py")
- Agent spoken responses
- Channel messages from both sides
- Current state indicator (IDLE / LISTENING / THINKING / SPEAKING)

Tool calls are collapsed when they arrive in bursts ("Viewing 6 files..." with the option to expand).

## Architecture

### Two processes

The voice runtime (existing `proxy` process) and the channel UI (`proxy channel`) are separate processes. They communicate through a shared event stream.

**Event stream:** The voice runtime writes events to a Unix domain socket or an append-only file (`~/.proxy/events.jsonl`). Each line is a JSON event with a timestamp, type, and content. The channel UI tails this stream and renders it.

**Text inbox:** The channel UI writes user input to a shared inbox file (`~/.proxy/inbox`). The voice runtime checks this file when building the next Copilot prompt. After reading, the inbox is cleared.

### Agent-side integration

The bootstrap instructions tell the agent about the channel:
- "You have access to a shared text channel with the user. When the user mentions the channel, its contents will be included in their prompt. When you need to share code, URLs, or structured content, wrap it in `[channel]...[/channel]` tags."
- The bridge parses `[channel]...[/channel]` tags from the agent's response, writes the content to the event stream as a channel message, strips the tags from TTS text, and replaces them with a spoken note.

### Event types for the stream

| Event | Source | Displayed as |
|---|---|---|
| `user_prompt` | STT final | "You: {text}" |
| `agent_thought` | Bridge | "🧠 {text}" |
| `agent_tool_call` | Bridge | "🔧 {title}" |
| `agent_partial` | Bridge | (accumulated into agent response) |
| `agent_response` | Bridge | "Proxy: {text}" |
| `channel_in` | Channel UI | "[channel] {content}" |
| `channel_out` | Bridge | "[channel] {content}" |
| `state_change` | Orchestrator | State indicator update |

## CLI commands

| Command | Purpose |
|---|---|
| `proxy channel` | Launch the live terminal UI |
| `proxy send "text"` | Quick-send text to the channel without opening the UI |
| `proxy send -` | Pipe content from stdin to the channel |

## Tech considerations

- **TUI framework:** `textual` (Python, rich terminal UI) for the full channel experience. Falls back to plain scrolling output if textual isn't installed.
- **Event format:** Newline-delimited JSON for simplicity and streaming compatibility.
- **Cleanup:** Events older than the current session are pruned on startup.
- **Multiple channels:** Not needed for v1. One channel per Proxy instance.

## Implementation phases

### Phase 1: Event stream
Add event writing to the voice runtime. Every user prompt, agent thought, tool call, and response is written to `~/.proxy/events.jsonl`. No UI yet — just the data layer.

### Phase 2: Basic channel CLI
`proxy channel` tails the event stream and prints formatted events to the terminal. Read-only, no input. `proxy send` writes to the inbox.

### Phase 3: Text handoff
Bridge reads inbox contents and prepends to Copilot prompts. Bridge parses `[channel]` tags from responses and writes to the event stream. Bootstrap instructions updated.

### Phase 4: Rich TUI
Replace plain output with a `textual` app: scrollable history, input bar, state indicator, collapsible tool call groups.
