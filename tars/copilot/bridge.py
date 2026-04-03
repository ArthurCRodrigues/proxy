from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from tars.observability.logger import get_logger
from tars.orchestrator.event_bus import EventBus
from tars.types import Event, EventType


def _default_instructions_path() -> str:
    return str(Path(__file__).resolve().parents[2] / "copilot-instructions.md")


@dataclass
class CopilotSessionHandle:
    session_id: str


@dataclass
class _AcpPromptState:
    turn_id: str | None
    text_parts: list[str]
    emit_events: bool


class CopilotBridge:
    def __init__(
        self,
        event_bus: EventBus,
        command: str = "copilot",
        model: str = "",
        allow_all: bool = True,
        instructions_path: str = _default_instructions_path(),
        on_session_exit: Callable[[str, int], Awaitable[None]] | None = None,
        on_assistant_partial: Callable[[str], None] | None = None,
        on_assistant_final: Callable[[str], None] | None = None,
    ) -> None:
        self._event_bus = event_bus
        self._command = command
        self._model = model
        self._allow_all = allow_all
        self._instructions_path = instructions_path
        self._logger = get_logger("proxy.copilot.bridge")
        self._active_task: asyncio.Task[None] | None = None
        self._active_session: CopilotSessionHandle | None = None
        self._bootstrapped_sessions: set[str] = set()
        self._acp_proc: asyncio.subprocess.Process | None = None
        self._acp_reader_task: asyncio.Task[None] | None = None
        self._acp_request_id = 0
        self._acp_pending: dict[int, asyncio.Future[object]] = {}
        self._acp_prompt_states: dict[str, _AcpPromptState] = {}
        self._acp_protocol_version = 1
        self._acp_initialized = False
        self._on_session_exit = on_session_exit
        self._on_assistant_partial = on_assistant_partial
        self._on_assistant_final = on_assistant_final

    async def prewarm_session(self) -> CopilotSessionHandle:
        session_id = await self._acp_new_session()
        return CopilotSessionHandle(session_id=session_id)

    async def ensure_session(self) -> CopilotSessionHandle:
        if self._active_session is None:
            self._active_session = await self.prewarm_session()
        return self._active_session

    async def reset_session(self) -> CopilotSessionHandle:
        await self.interrupt_turn()
        self._active_session = await self.prewarm_session()
        return self._active_session

    async def send_user_turn(self, text: str, turn_id: str | None = None) -> None:
        session = await self.ensure_session()
        include_bootstrap = session.session_id not in self._bootstrapped_sessions
        if self._active_task is not None and not self._active_task.done():
            await self.interrupt_turn()
        self._active_task = asyncio.create_task(
            self._run_prompt(text, session.session_id, turn_id, include_bootstrap)
        )

    async def interrupt_turn(self) -> None:
        if self._active_task is not None:
            if not self._active_task.done():
                self._active_task.cancel()
                try:
                    await self._active_task
                except asyncio.CancelledError:
                    pass
            self._active_task = None
        if self._active_session is not None:
            await self._acp_notify("session/cancel", {"sessionId": self._active_session.session_id})
        await self._event_bus.publish(Event(type=EventType.INTERRUPT_ACK))

    async def hard_stop(self) -> None:
        await self.interrupt_turn()
        self._active_session = None
        self._bootstrapped_sessions.clear()
        await self._stop_acp()

    async def rollover_session(self) -> CopilotSessionHandle:
        handle = await self.prewarm_session()
        self._active_session = handle
        return handle

    async def _run_prompt(
        self,
        prompt: str,
        session_id: str,
        turn_id: str | None,
        include_bootstrap: bool,
    ) -> None:
        await self._run_prompt_acp(prompt, session_id, turn_id, include_bootstrap)

    async def _run_prompt_acp(
        self,
        prompt: str,
        session_id: str,
        turn_id: str | None,
        include_bootstrap: bool,
    ) -> None:
        effective_prompt = self._with_bootstrap_instructions(prompt, include_bootstrap)
        self._logger.info(
            "COPILOT_PROMPT session=%s turn=%s bootstrap=%s prompt=%r",
            session_id,
            turn_id,
            include_bootstrap,
            effective_prompt,
        )
        self._acp_prompt_states[session_id] = _AcpPromptState(
            turn_id=turn_id,
            text_parts=[],
            emit_events=True,
        )
        try:
            result = await self._acp_send_request(
                "session/prompt",
                {
                    "sessionId": session_id,
                    "prompt": [{"type": "text", "text": effective_prompt}],
                },
            )
            stop_reason = str(result.get("stopReason", "end_turn")).strip().lower()
            state = self._acp_prompt_states.pop(session_id, None)
            full_text = "".join(state.text_parts).strip() if state is not None else ""
            await self._emit_assistant_final(session_id, turn_id, full_text)
            if include_bootstrap and stop_reason == "end_turn":
                self._bootstrapped_sessions.add(session_id)
            rc = 0 if stop_reason == "end_turn" else 1
            await self._event_bus.publish(
                Event(
                    type=EventType.SESSION_EXIT,
                    session_id=session_id,
                    turn_id=turn_id,
                    payload={"code": rc, "stop_reason": stop_reason},
                )
            )
            if self._on_session_exit is not None:
                await self._on_session_exit(session_id, rc)
        except asyncio.CancelledError:
            self._acp_prompt_states.pop(session_id, None)
            await self._acp_notify("session/cancel", {"sessionId": session_id})
            raise
        except Exception as exc:
            self._acp_prompt_states.pop(session_id, None)
            await self._event_bus.publish(
                Event(
                    type=EventType.ERROR,
                    session_id=session_id,
                    turn_id=turn_id,
                    payload={"message": f"Copilot ACP prompt failed: {exc}"},
                )
            )
            await self._event_bus.publish(
                Event(
                    type=EventType.SESSION_EXIT,
                    session_id=session_id,
                    turn_id=turn_id,
                    payload={"code": 1, "stop_reason": "error"},
                )
            )
            if self._on_session_exit is not None:
                await self._on_session_exit(session_id, 1)

    async def _run_bootstrap_prompt_acp(self, session_id: str) -> None:
        prompt = self._with_bootstrap_instructions(
            "Bootstrap this session only. Reply with READY.",
            include_bootstrap=True,
        )
        self._logger.info("COPILOT_BOOTSTRAP_START session=%s", session_id)
        self._acp_prompt_states[session_id] = _AcpPromptState(
            turn_id=None,
            text_parts=[],
            emit_events=False,
        )
        try:
            result = await self._acp_send_request(
                "session/prompt",
                {"sessionId": session_id, "prompt": [{"type": "text", "text": prompt}]},
            )
            stop_reason = str(result.get("stopReason", "end_turn")).strip().lower()
            self._acp_prompt_states.pop(session_id, None)
            if stop_reason == "end_turn":
                self._bootstrapped_sessions.add(session_id)
                self._logger.info("COPILOT_BOOTSTRAP_READY session=%s", session_id)
            else:
                self._logger.warning(
                    "COPILOT_BOOTSTRAP_FAILED session=%s stop_reason=%s",
                    session_id,
                    stop_reason,
                )
        except asyncio.CancelledError:
            self._acp_prompt_states.pop(session_id, None)
            await self._acp_notify("session/cancel", {"sessionId": session_id})
            raise
        except Exception as exc:
            self._acp_prompt_states.pop(session_id, None)
            self._logger.warning(
                "COPILOT_BOOTSTRAP_FAILED session=%s err=%s",
                session_id,
                exc,
            )

    async def _emit_assistant_partial(
        self,
        session_id: str,
        turn_id: str | None,
        text: str,
    ) -> None:
        if not text:
            return
        if self._on_assistant_partial is not None:
            self._on_assistant_partial(text)
        await self._event_bus.publish(
            Event(
                type=EventType.ASSISTANT_PARTIAL,
                session_id=session_id,
                turn_id=turn_id,
                payload={"text": text},
            )
        )

    async def _emit_assistant_final(
        self,
        session_id: str,
        turn_id: str | None,
        raw_text: str,
    ) -> None:
        final_text = raw_text
        if self._on_assistant_final is not None and final_text:
            self._on_assistant_final(final_text)
        await self._event_bus.publish(
            Event(
                type=EventType.ASSISTANT_FINAL,
                session_id=session_id,
                turn_id=turn_id,
                payload={"text": final_text},
            )
        )

    async def _acp_ensure_started(self) -> None:
        if (
            self._acp_proc is not None
            and self._acp_proc.returncode is None
            and self._acp_initialized
        ):
            return
        cmd: list[str] = [self._command, "--acp", "--stdio"]
        if self._allow_all:
            cmd.append("--allow-all")
        if self._model:
            cmd.extend(["--model", self._model])
        self._logger.info("Starting Copilot ACP process")
        self._acp_proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self._acp_initialized = False
        self._acp_reader_task = asyncio.create_task(self._acp_reader_loop())
        init_result = await self._acp_send_request_raw(
            "initialize",
            {
                "protocolVersion": self._acp_protocol_version,
                "clientCapabilities": {},
                "clientInfo": {"name": "tars", "version": "0.1.0"},
            },
        )
        protocol = int(init_result.get("protocolVersion", 1))
        self._acp_protocol_version = protocol
        self._acp_initialized = True
        self._logger.info("Copilot ACP initialized (protocol=%s)", protocol)

    async def _acp_send_json(self, payload: dict) -> None:
        if self._acp_proc is None or self._acp_proc.stdin is None:
            raise RuntimeError("ACP process is not available")
        line = json.dumps(payload, separators=(",", ":")) + "\n"
        self._acp_proc.stdin.write(line.encode("utf-8"))
        await self._acp_proc.stdin.drain()

    async def _acp_send_request_raw(self, method: str, params: dict) -> dict:
        if self._acp_proc is None:
            raise RuntimeError("ACP process is not available")
        self._acp_request_id += 1
        req_id = self._acp_request_id
        future: asyncio.Future[object] = asyncio.get_running_loop().create_future()
        self._acp_pending[req_id] = future
        await self._acp_send_json(
            {
                "jsonrpc": "2.0",
                "id": req_id,
                "method": method,
                "params": params,
            }
        )
        result = await future
        if isinstance(result, dict):
            return result
        return {}

    async def _acp_send_request(self, method: str, params: dict) -> dict:
        await self._acp_ensure_started()
        return await self._acp_send_request_raw(method, params)

    async def _acp_notify(self, method: str, params: dict) -> None:
        if self._acp_proc is None or self._acp_proc.returncode is not None:
            return
        await self._acp_send_json({"jsonrpc": "2.0", "method": method, "params": params})

    async def _acp_new_session(self) -> str:
        result = await self._acp_send_request(
            "session/new",
            {
                "cwd": os.getcwd(),
                "mcpServers": [],
            },
        )
        session_id = str(result.get("sessionId", "")).strip()
        if not session_id:
            raise RuntimeError("ACP session/new did not return a sessionId")
        
        await self._run_bootstrap_prompt_acp(session_id)

        return session_id

    async def _acp_reader_loop(self) -> None:
        proc = self._acp_proc
        if proc is None or proc.stdout is None:
            return
        try:
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                raw = line.decode("utf-8", errors="ignore").strip()
                if not raw:
                    continue
                try:
                    message = json.loads(raw)
                except json.JSONDecodeError:
                    self._logger.debug("Ignoring non-JSON ACP line: %r", raw)
                    continue

                if "id" in message and ("result" in message or "error" in message):
                    msg_id = message.get("id")
                    if isinstance(msg_id, int):
                        future = self._acp_pending.pop(msg_id, None)
                        if future is not None and not future.done():
                            if "error" in message:
                                future.set_exception(
                                    RuntimeError(f"ACP error: {message.get('error')}")
                                )
                            else:
                                future.set_result(message.get("result"))
                    continue

                method = str(message.get("method", ""))
                if method == "session/request_permission":
                    await self._handle_acp_permission_request(message)
                    continue
                if method == "session/update":
                    await self._handle_acp_session_update(message.get("params", {}))
                    continue
        except asyncio.CancelledError:
            pass
        finally:
            for _, future in list(self._acp_pending.items()):
                if not future.done():
                    future.set_exception(RuntimeError("ACP connection closed"))
            self._acp_pending.clear()
            self._acp_initialized = False

    async def _handle_acp_permission_request(self, message: dict) -> None:
        msg_id = message.get("id")
        if not isinstance(msg_id, int):
            return
        outcome = "allow" if self._allow_all else "cancelled"
        await self._acp_send_json(
            {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {"outcome": {"outcome": outcome}},
            }
        )

    async def _handle_acp_session_update(self, params: dict) -> None:
        session_id = str(params.get("sessionId", "")).strip()
        if not session_id:
            return
        state = self._acp_prompt_states.get(session_id)
        if state is None:
            return
        update = params.get("update", {})
        if not isinstance(update, dict):
            return
        session_update = str(update.get("sessionUpdate", "")).strip()
        if session_update != "agent_message_chunk":
            return
        content = update.get("content", {})
        if not isinstance(content, dict):
            return
        if content.get("type") != "text":
            return
        text = str(content.get("text", ""))
        if not text:
            return
        state.text_parts.append(text)
        if state.emit_events:
            await self._emit_assistant_partial(session_id, state.turn_id, text)

    async def _stop_acp(self) -> None:
        if self._acp_reader_task is not None and not self._acp_reader_task.done():
            self._acp_reader_task.cancel()
            try:
                await self._acp_reader_task
            except asyncio.CancelledError:
                pass
        self._acp_reader_task = None
        if self._acp_proc is not None and self._acp_proc.returncode is None:
            self._acp_proc.terminate()
            try:
                await asyncio.wait_for(self._acp_proc.wait(), timeout=2.0)
            except TimeoutError:
                self._acp_proc.kill()
                await self._acp_proc.wait()
        self._acp_proc = None

    def _with_bootstrap_instructions(self, prompt: str, include_bootstrap: bool) -> str:
        if not include_bootstrap:
            return prompt

        path = Path(self._instructions_path).expanduser()
        if not path.exists():
            self._logger.warning(
                "Copilot instructions file not found at %s; sending raw prompt",
                path,
            )
            return prompt

        content = path.read_text(encoding="utf-8").strip()
        if not content:
            self._logger.warning(
                "Copilot instructions file empty at %s; sending raw prompt",
                path,
            )
            return prompt

        return (
            f"System bootstrap instructions:\\n{content}\\n\\n"
            f"User request (verbatim STT):\\n{prompt}"
        )
