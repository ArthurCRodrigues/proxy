# Copilot Integration (ACP)

Proxy communicates with GitHub Copilot CLI exclusively through the Agent Control Protocol (ACP). The `CopilotBridge` manages the ACP subprocess, JSON-RPC transport, session lifecycle, and bootstrap instructions.

## ACP process

The bridge starts a single long-lived subprocess:

```
copilot --acp --stdio [--allow-all] [--model <model>]
```

Communication happens over stdio using newline-delimited JSON-RPC 2.0. The bridge writes requests to stdin and reads responses/notifications from stdout. A background `_acp_reader_loop` task continuously reads stdout and dispatches messages.

The process is started lazily on the first operation that needs it (`_acp_ensure_started`). Once started, it stays alive for the lifetime of the Proxy process. On shutdown, `hard_stop()` terminates it (with a 2-second grace period before kill).

## JSON-RPC protocol

The bridge implements a minimal JSON-RPC 2.0 client:

**Requests** (`_acp_send_request`) have an auto-incrementing integer `id`. The bridge creates an `asyncio.Future` for each request and stores it in `_acp_pending`. When the reader loop receives a response with a matching `id`, it resolves the future.

**Notifications** (`_acp_notify`) have no `id` and expect no response. Used for `session/cancel`.

**Incoming notifications** from Copilot are dispatched by method name:
- `session/update` → streaming response chunks.
- `session/request_permission` → tool/action permission requests.

### Initialization

On first use, the bridge sends an `initialize` request:

```json
{
  "method": "initialize",
  "params": {
    "protocolVersion": 1,
    "clientCapabilities": {},
    "clientInfo": {"name": "proxy", "version": "0.1.0"}
  }
}
```

The response contains the negotiated `protocolVersion`, which is stored for future use.

## Session management

### Session pool

`SessionPool` manages two session slots:

- **Standby** — a pre-created session ready to be activated. Created at startup and after each wake cycle.
- **Active** — the session currently in use for the conversation.

The lifecycle:
1. At startup: `ensure_standby()` prewarms a standby session.
2. On wake: `activate_standby()` promotes standby to active. `rollover()` prewarms a new standby in the background.
3. On "new session" voice command: `reset_active()` cancels everything and creates a fresh session.

This pattern minimizes latency on wake — the session already exists and is bootstrapped before the user starts speaking.

### Session creation

`session/new` creates a session on the ACP side:

```json
{
  "method": "session/new",
  "params": {
    "cwd": "<current working directory>",
    "mcpServers": []
  }
}
```

The response contains a `sessionId` string that identifies the session for all subsequent operations.

### Session bootstrap

Each session is bootstrapped exactly once with system instructions. The bootstrap prompt is:

```
System bootstrap instructions:
<contents of copilot-instructions.md or default instructions>

User request (verbatim STT):
Bootstrap this session only. Reply with READY.
```

If no instructions file is found at the configured path (`PROXY_COPILOT_INSTRUCTIONS_PATH`, default `<project_root>/copilot-instructions.md`), the bridge falls back to built-in default instructions that tell Copilot it's a voice assistant and should respond in plain conversational text without markdown or formatting.

Bootstrap runs as a background task (`bootstrap_active_session_background`). The `_AcpPromptState` for bootstrap has `emit_events=False`, so no `ASSISTANT_PARTIAL`/`ASSISTANT_FINAL` events are published to the bus — the bootstrap response is silently consumed.

The set `_bootstrapped_sessions` tracks which sessions have been bootstrapped. On the first real user turn, if the session hasn't been bootstrapped yet (e.g. bootstrap is still in flight), `send_user_turn` waits up to 800ms for it to complete before proceeding.

## Prompt execution

When the orchestrator forwards a user transcript via `send_user_turn(text, turn_id)`:

1. The session is ensured (lazy creation if needed).
2. If a bootstrap task is running, wait up to 800ms for it.
3. Determine if bootstrap instructions should be included (first turn on an un-bootstrapped session).
4. Cancel any in-flight prompt task.
5. Create a new `_run_prompt` task.

The prompt is sent via `session/prompt`:

```json
{
  "method": "session/prompt",
  "params": {
    "sessionId": "<session_id>",
    "prompt": [{"type": "text", "text": "<effective_prompt>"}]
  }
}
```

### Streaming responses

As Copilot generates its response, the ACP process sends `session/update` notifications:

```json
{
  "method": "session/update",
  "params": {
    "sessionId": "<session_id>",
    "update": {
      "sessionUpdate": "agent_message_chunk",
      "content": {"type": "text", "text": "<chunk>"}
    }
  }
}
```

The bridge's `_handle_acp_session_update` method:
1. Looks up the `_AcpPromptState` for the session.
2. Appends the text chunk to `state.text_parts`.
3. If `emit_events` is True, calls `_emit_assistant_partial` which invokes the callback and publishes an `ASSISTANT_PARTIAL` event.

When the `session/prompt` request completes (the future resolves), the bridge:
1. Joins all accumulated `text_parts` into the final text.
2. Calls `_emit_assistant_final` which invokes the callback and publishes `ASSISTANT_FINAL`.
3. Marks the session as bootstrapped if applicable.

### Cancellation

If a prompt needs to be cancelled (e.g. user starts a new turn before the previous one finishes), the bridge:
1. Cancels the asyncio task.
2. Sends a `session/cancel` notification to the ACP process.

### Permission requests

When Copilot needs permission to use a tool or perform an action, it sends a `session/request_permission` message. If `allow_all` is True (the default, configured via `PROXY_COPILOT_ALLOW_ALL`), the bridge auto-responds with `"allow"`. Otherwise it responds with `"cancelled"`.

## Error handling

If the ACP prompt fails with an exception, the bridge:
1. Cleans up the prompt state.
2. Logs the error.
3. Publishes an `ERROR` event to the bus (which the state machine treats as a no-op).

The conversation can continue — the next wake cycle will use the same session.
