# Copilot Integration (ACP)

Proxy communicates with GitHub Copilot CLI through the Agent Control Protocol (ACP) over a single long-lived subprocess.

## ACP process

The bridge starts `copilot --acp --stdio [--allow-all] [--model <model>]` and communicates via newline-delimited JSON-RPC 2.0 over stdio. The process starts lazily on first use and stays alive for the lifetime of Proxy.

## Session management

`SessionPool` manages a single active session. At startup, `ensure_active()` creates a session and bootstraps it with system instructions in the background. The same session is reused across all wake cycles for conversational continuity. A new session is only created on explicit "new session" voice command.

Bootstrap sends a priming prompt with instructions from `copilot-instructions.md` (or built-in defaults telling Copilot to respond conversationally without markdown). The set `_bootstrapped_sessions` ensures each session is bootstrapped exactly once.

## Prompt execution

When the orchestrator forwards a user transcript via `send_user_turn`:
1. Ensure session exists, wait up to 800ms for in-flight bootstrap.
2. Cancel any previous in-flight prompt.
3. Send `session/prompt` with the text (prepended with bootstrap instructions on first turn).
4. Stream responses via `session/update` notifications.

## Streaming events

The ACP reader loop processes all `session/update` notifications:

| `sessionUpdate` | Handling |
|---|---|
| `agent_message_chunk` | Text appended to response, `on_assistant_partial` callback fired |
| `agent_thought_chunk` | Logged as `COPILOT_THOUGHT`, spoken via `on_narration` callback (deduplicated) |
| `tool_call` | Logged as `COPILOT_TOOL_CALL` with title and status |
| `tool_call_update` | Logged as `COPILOT_TOOL_UPDATE` with status |

When the `session/prompt` request completes, all accumulated text parts are joined and `on_assistant_final` is fired.

## Interruption

`hard_stop_turn()` cancels the active prompt task and sends `session/cancel` to the ACP process. The session itself survives — only the current turn is cancelled.

## Permission requests

When Copilot needs permission for a tool action, the bridge auto-responds with "allow" (when `copilot_allow_all` is true) or "cancelled".
