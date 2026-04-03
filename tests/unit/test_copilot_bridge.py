from __future__ import annotations

import asyncio
from pathlib import Path

from tars.copilot.bridge import CopilotBridge, CopilotSessionHandle, _AcpPromptState
from tars.orchestrator.event_bus import EventBus
from tars.types import EventType


def test_bridge_prewarm_and_rollover() -> None:
    async def _run() -> None:
        bus = EventBus()
        bridge = CopilotBridge(event_bus=bus)
        session_ids = iter(("s1", "s2"))

        async def fake_acp_new_session() -> str:
            return next(session_ids)

        bridge._acp_new_session = fake_acp_new_session  # type: ignore[assignment]
        handle = await bridge.prewarm_session()
        assert handle.session_id
        active = await bridge.activate_session_on_wake(handle)
        assert active.session_id == handle.session_id
        rolled = await bridge.rollover_session()
        assert rolled.session_id

    asyncio.run(_run())


def test_bridge_interrupt_publishes_ack() -> None:
    async def _run() -> None:
        bus = EventBus()
        bridge = CopilotBridge(event_bus=bus)
        await bridge.interrupt_turn()
        event = await bus.next_event()
        assert event.type == EventType.INTERRUPT_ACK
        bus.task_done()

    asyncio.run(_run())


def test_bridge_bootstrap_instructions_wrap_prompt(tmp_path: Path) -> None:
    bus = EventBus()
    instructions = tmp_path / "copilot-instructions.md"
    instructions.write_text("Speak concise.\nUse repo context.", encoding="utf-8")

    bridge = CopilotBridge(
        event_bus=bus,
        bootstrap_instructions=True,
        instructions_path=str(instructions),
    )
    wrapped = bridge._with_bootstrap_instructions("Fix issue 123", include_bootstrap=True)
    assert "System bootstrap instructions:" in wrapped
    assert "Speak concise." in wrapped
    assert "User request (verbatim STT):" in wrapped
    assert wrapped.endswith("Fix issue 123")


def test_bridge_bootstrap_disabled_keeps_raw_prompt() -> None:
    bus = EventBus()
    bridge = CopilotBridge(event_bus=bus, bootstrap_instructions=False)
    assert bridge._with_bootstrap_instructions("hello", include_bootstrap=True) == "hello"


def test_bridge_bootstrap_skipped_when_not_requested(tmp_path: Path) -> None:
    bus = EventBus()
    instructions = tmp_path / "copilot-instructions.md"
    instructions.write_text("Use speech style.", encoding="utf-8")
    bridge = CopilotBridge(
        event_bus=bus,
        bootstrap_instructions=True,
        instructions_path=str(instructions),
    )
    assert bridge._with_bootstrap_instructions("hello", include_bootstrap=False) == "hello"


def test_bridge_send_user_turn_bootstrap_only_first_turn() -> None:
    async def _run() -> None:
        bus = EventBus()
        bridge = CopilotBridge(event_bus=bus, bootstrap_instructions=False)
        bridge._active_session = CopilotSessionHandle(session_id="sess-1")
        captured: list[tuple[bool, str]] = []

        async def fake_run_prompt(
            prompt: str,
            session_id: str,
            turn_id: str | None,
            include_bootstrap: bool,
        ) -> None:
            captured.append((include_bootstrap, session_id))

        bridge._run_prompt = fake_run_prompt  # type: ignore[assignment]
        await bridge.send_user_turn("first")
        await bridge.send_user_turn("second")
        await asyncio.sleep(0)

        assert len(captured) == 1
        assert captured[0][0] is True
        bridge._bootstrapped_sessions.add(captured[0][1])
        await bridge.send_user_turn("third")
        await asyncio.sleep(0)
        assert len(captured) == 2
        assert captured[1][0] is False
        assert captured[0][1] == captured[1][1]

    asyncio.run(_run())


def test_bridge_acp_prompt_state_accumulates_text() -> None:
    async def _run() -> None:
        bus = EventBus()
        bridge = CopilotBridge(event_bus=bus, bootstrap_instructions=False)
        session_id = "sess-1"
        bridge._acp_prompt_states[session_id] = _AcpPromptState(
            turn_id="t1",
            text_parts=[],
            emit_events=False,
        )
        await bridge._handle_acp_session_update(
            {
                "sessionId": session_id,
                "update": {
                    "sessionUpdate": "agent_message_chunk",
                    "content": {"type": "text", "text": "Hello"},
                },
            }
        )
        state = bridge._acp_prompt_states[session_id]
        assert state.text_parts == ["Hello"]

    asyncio.run(_run())


def test_emit_assistant_final_publishes_text_payload() -> None:
    async def _run() -> None:
        bus = EventBus()
        bridge = CopilotBridge(
            event_bus=bus,
            bootstrap_instructions=False,
        )
        await bridge._emit_assistant_final("s1", "t1", "Plain text without contract")
        event = await bus.next_event()
        assert event.type == EventType.ASSISTANT_FINAL
        assert event.payload == {"text": "Plain text without contract"}
        bus.task_done()

    asyncio.run(_run())


def test_bridge_acp_new_session_runs_bootstrap_when_enabled() -> None:
    async def _run() -> None:
        bus = EventBus()
        bridge = CopilotBridge(
            event_bus=bus,
            bootstrap_instructions=True,
        )
        captured: list[str] = []

        async def fake_send_request(method: str, params: dict) -> dict:
            assert method == "session/new"
            assert params["cwd"]
            return {"sessionId": "sess-bootstrap"}

        async def fake_run_bootstrap_prompt_acp(session_id: str) -> None:
            captured.append(session_id)

        bridge._acp_send_request = fake_send_request  # type: ignore[assignment]
        bridge._run_bootstrap_prompt_acp = fake_run_bootstrap_prompt_acp  # type: ignore[assignment]

        session_id = await bridge._acp_new_session()
        assert session_id == "sess-bootstrap"
        assert captured == ["sess-bootstrap"]

    asyncio.run(_run())


def test_bridge_acp_new_session_skips_bootstrap_when_disabled() -> None:
    async def _run() -> None:
        bus = EventBus()
        bridge = CopilotBridge(
            event_bus=bus,
            bootstrap_instructions=False,
        )
        captured: list[str] = []

        async def fake_send_request(method: str, params: dict) -> dict:
            assert method == "session/new"
            assert params["cwd"]
            return {"sessionId": "sess-no-bootstrap"}

        async def fake_run_bootstrap_prompt_acp(session_id: str) -> None:
            captured.append(session_id)

        bridge._acp_send_request = fake_send_request  # type: ignore[assignment]
        bridge._run_bootstrap_prompt_acp = fake_run_bootstrap_prompt_acp  # type: ignore[assignment]

        session_id = await bridge._acp_new_session()
        assert session_id == "sess-no-bootstrap"
        assert captured == []

    asyncio.run(_run())
