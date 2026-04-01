from __future__ import annotations

import asyncio
from pathlib import Path
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from uuid import uuid4

from tars.copilot.contract import parse_assistant_final_contract
from tars.copilot.parser import parse_jsonl_event
from tars.observability.logger import get_logger
from tars.orchestrator.event_bus import EventBus
from tars.types import Event, EventType


@dataclass
class CopilotSessionHandle:
    session_id: str


class CopilotBridge:
    def __init__(
        self,
        event_bus: EventBus,
        command: str = "copilot",
        model: str = "",
        allow_all: bool = True,
        bootstrap_instructions: bool = True,
        instructions_path: str = "~/.copilot/copilot-instructions.md",
        enable_final_contract: bool = True,
        on_session_exit: Callable[[str, int], Awaitable[None]] | None = None,
        on_assistant_partial: Callable[[str], None] | None = None,
        on_assistant_final: Callable[[str], None] | None = None,
    ) -> None:
        self._event_bus = event_bus
        self._command = command
        self._model = model
        self._allow_all = allow_all
        self._bootstrap_instructions = bootstrap_instructions
        self._instructions_path = instructions_path
        self._enable_final_contract = enable_final_contract
        self._logger = get_logger("tars.copilot.bridge")
        self._active_task: asyncio.Task[None] | None = None
        self._bootstrap_task: asyncio.Task[None] | None = None
        self._active_session: CopilotSessionHandle | None = None
        self._bootstrapped_sessions: set[str] = set()
        self._on_session_exit = on_session_exit
        self._on_assistant_partial = on_assistant_partial
        self._on_assistant_final = on_assistant_final

    async def prewarm_session(self) -> CopilotSessionHandle:
        return CopilotSessionHandle(session_id=str(uuid4()))

    async def activate_session_on_wake(self, handle: CopilotSessionHandle) -> CopilotSessionHandle:
        self._active_session = handle
        return handle

    async def ensure_session(self) -> CopilotSessionHandle:
        if self._active_session is None:
            self._active_session = await self.prewarm_session()
        return self._active_session

    async def reset_session(self) -> CopilotSessionHandle:
        await self.interrupt_turn()
        await self._cancel_bootstrap_task()
        self._active_session = await self.prewarm_session()
        return self._active_session

    async def send_user_turn(self, text: str, turn_id: str | None = None) -> None:
        session = await self.ensure_session()
        if self._bootstrap_task is not None and not self._bootstrap_task.done():
            try:
                await asyncio.wait_for(asyncio.shield(self._bootstrap_task), timeout=0.8)
            except TimeoutError:
                await self._cancel_bootstrap_task()
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
        await self._event_bus.publish(Event(type=EventType.INTERRUPT_ACK))

    async def hard_stop(self) -> None:
        await self.interrupt_turn()
        await self._cancel_bootstrap_task()
        self._active_session = None
        self._bootstrapped_sessions.clear()

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
        effective_prompt = self._with_bootstrap_instructions(prompt, include_bootstrap)
        cmd: list[str] = [
            self._command,
            "--output-format",
            "json",
            f"--resume={session_id}",
            "-p",
            effective_prompt,
        ]
        if self._allow_all:
            cmd.append("--allow-all")
        if self._model:
            cmd.extend(["--model", self._model])

        self._logger.info(
            "COPILOT_PROMPT session=%s turn=%s bootstrap=%s prompt=%r",
            session_id,
            turn_id,
            include_bootstrap,
            effective_prompt,
        )
        self._logger.debug("Launching Copilot prompt process (session=%s turn=%s)", session_id, turn_id)
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        assert proc.stdout is not None
        assert proc.stderr is not None

        try:
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                parsed = parse_jsonl_event(line.decode("utf-8", errors="ignore"))
                if parsed is None:
                    continue
                if parsed.event_type == "assistant.message_delta" and parsed.content:
                    if self._on_assistant_partial is not None:
                        self._on_assistant_partial(parsed.content)
                    await self._event_bus.publish(
                        Event(
                            type=EventType.ASSISTANT_PARTIAL,
                            session_id=session_id,
                            turn_id=turn_id,
                            payload={"text": parsed.content},
                        )
                    )
                if parsed.event_type == "assistant.message" and parsed.content:
                    contract = parse_assistant_final_contract(parsed.content)
                    final_text = contract.spoken_text if self._enable_final_contract else parsed.content
                    final_status = contract.status if self._enable_final_contract else "handoff"
                    if self._on_assistant_final is not None:
                        self._on_assistant_final(final_text)
                    await self._event_bus.publish(
                        Event(
                            type=EventType.ASSISTANT_FINAL,
                            session_id=session_id,
                            turn_id=turn_id,
                            payload={
                                "text": final_text,
                                "status": final_status,
                                "contract_detected": contract.contract_detected,
                                "raw_text": contract.raw_text,
                            },
                        )
                    )

            stderr_out = (await proc.stderr.read()).decode("utf-8", errors="ignore").strip()
            rc = await proc.wait()
            if rc == 0 and include_bootstrap:
                self._bootstrapped_sessions.add(session_id)
            if rc != 0:
                await self._event_bus.publish(
                    Event(
                        type=EventType.ERROR,
                        session_id=session_id,
                        turn_id=turn_id,
                        payload={"message": f"Copilot process failed ({rc}): {stderr_out}"},
                    )
                )
            await self._event_bus.publish(
                Event(
                    type=EventType.SESSION_EXIT,
                    session_id=session_id,
                    turn_id=turn_id,
                    payload={"code": rc},
                )
            )
            if self._on_session_exit is not None:
                await self._on_session_exit(session_id, rc)
        except asyncio.CancelledError:
            if proc.returncode is None:
                proc.kill()
                await proc.wait()
            raise

    async def bootstrap_active_session_background(self) -> None:
        session = await self.ensure_session()
        session_id = session.session_id
        if session_id in self._bootstrapped_sessions:
            return
        if self._bootstrap_task is not None and not self._bootstrap_task.done():
            return
        self._bootstrap_task = asyncio.create_task(self._run_bootstrap_prompt(session_id))

    async def _run_bootstrap_prompt(self, session_id: str) -> None:
        prompt = self._with_bootstrap_instructions(
            "Bootstrap this session only. Reply with READY.",
            include_bootstrap=True,
        )
        cmd: list[str] = [
            self._command,
            "--output-format",
            "json",
            f"--resume={session_id}",
            "-p",
            prompt,
        ]
        if self._allow_all:
            cmd.append("--allow-all")
        if self._model:
            cmd.extend(["--model", self._model])
        self._logger.info("COPILOT_BOOTSTRAP_START session=%s", session_id)
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        assert proc.stdout is not None
        assert proc.stderr is not None
        try:
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
            stderr_out = (await proc.stderr.read()).decode("utf-8", errors="ignore").strip()
            rc = await proc.wait()
            if rc == 0:
                self._bootstrapped_sessions.add(session_id)
                self._logger.info("COPILOT_BOOTSTRAP_READY session=%s", session_id)
            else:
                self._logger.warning(
                    "COPILOT_BOOTSTRAP_FAILED session=%s code=%s err=%s",
                    session_id,
                    rc,
                    stderr_out,
                )
        except asyncio.CancelledError:
            if proc.returncode is None:
                proc.kill()
                await proc.wait()
            raise

    async def _cancel_bootstrap_task(self) -> None:
        if self._bootstrap_task is None:
            return
        if not self._bootstrap_task.done():
            self._bootstrap_task.cancel()
            try:
                await self._bootstrap_task
            except asyncio.CancelledError:
                pass
        self._bootstrap_task = None

    def _with_bootstrap_instructions(self, prompt: str, include_bootstrap: bool) -> str:
        if not self._bootstrap_instructions or not include_bootstrap:
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

        if self._enable_final_contract:
            contract_instructions = (
                "Output contract for assistant.message final:\\n"
                "- End your final message with a single-line JSON object only on the last line.\\n"
                "- JSON schema: {\\\"tars_status\\\":\\\"working|handoff\\\",\\\"spoken\\\":\\\"<what to say out loud>\\\"}.\\n"
                "- Use tars_status=working when you are still executing the same user request and expect to continue automatically.\\n"
                "- Use tars_status=handoff when you are done and returning control to the user.\\n"
                "- Keep spoken concise and natural for voice playback.\\n"
                "- Do not wrap JSON in markdown fences."
            )
            return (
                f"System bootstrap instructions:\\n{content}\\n\\n"
                f"{contract_instructions}\\n\\n"
                f"User request (verbatim STT):\\n{prompt}"
            )

        return (
            f"System bootstrap instructions:\\n{content}\\n\\n"
            f"User request (verbatim STT):\\n{prompt}"
        )
