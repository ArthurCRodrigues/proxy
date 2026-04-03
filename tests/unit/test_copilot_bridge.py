from __future__ import annotations

import asyncio
from pathlib import Path

from proxy.copilot.bridge import CopilotBridge, _AcpPromptState
from proxy.orchestrator.event_bus import EventBus
from proxy.types import EventType


def test_bridge_bootstrap_instructions_wrap_prompt(tmp_path: Path) -> None:
    bus = EventBus()
    instructions = tmp_path / "copilot-instructions.md"
    instructions.write_text("Speak concise.\nUse repo context.", encoding="utf-8")

    bridge = CopilotBridge(
        event_bus=bus,
        instructions_path=str(instructions),
    )
    wrapped = bridge._with_bootstrap_instructions("Fix issue 123", include_bootstrap=True)
    assert "System bootstrap instructions:" in wrapped
    assert "Speak concise." in wrapped
    assert "User request (verbatim STT):" in wrapped
    assert wrapped.endswith("Fix issue 123")


def test_bridge_bootstrap_falls_back_to_default_when_no_file(tmp_path: Path) -> None:
    bus = EventBus()
    bridge = CopilotBridge(
        event_bus=bus,
        instructions_path=str(tmp_path / "nonexistent.md"),
    )
    wrapped = bridge._with_bootstrap_instructions("hello", include_bootstrap=True)
    assert "System bootstrap instructions:" in wrapped
    assert "voice assistant" in wrapped
    assert "hello" in wrapped


def test_bridge_bootstrap_skipped_when_not_requested(tmp_path: Path) -> None:
    bus = EventBus()
    instructions = tmp_path / "copilot-instructions.md"
    instructions.write_text("Use speech style.", encoding="utf-8")
    bridge = CopilotBridge(
        event_bus=bus,
        instructions_path=str(instructions),
    )
    assert bridge._with_bootstrap_instructions("hello", include_bootstrap=False) == "hello"


def test_bridge_send_user_turn_bootstrap_only_first_turn() -> None:
    async def _run() -> None:
        bus = EventBus()
        bridge = CopilotBridge(event_bus=bus)
        captured: list[tuple[bool, str]] = []

        async def fake_run_prompt(
            prompt: str,
            session_id: str,
            turn_id: str | None,
            include_bootstrap: bool,
        ) -> None:
            captured.append((include_bootstrap, session_id))

        bridge._run_prompt = fake_run_prompt  # type: ignore[assignment]
        from proxy.copilot.bridge import CopilotSessionHandle
        bridge._active_session = CopilotSessionHandle(session_id="test-session")

        await bridge.send_user_turn("first")
        await asyncio.sleep(0)

        assert len(captured) == 1
        assert captured[0][0] is True
        bridge._bootstrapped_sessions.add(captured[0][1])
        await bridge.send_user_turn("second")
        await asyncio.sleep(0)
        assert len(captured) == 2
        assert captured[1][0] is False
        assert captured[0][1] == captured[1][1]

    asyncio.run(_run())


def test_bridge_acp_prompt_state_accumulates_text() -> None:
    async def _run() -> None:
        bus = EventBus()
        bridge = CopilotBridge(event_bus=bus)
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
        bridge = CopilotBridge(event_bus=bus)
        await bridge._emit_assistant_final("s1", "t1", "Plain text without contract")
        event = await bus.next_event()
        assert event.type == EventType.ASSISTANT_FINAL
        assert event.payload == {"text": "Plain text without contract"}
        bus.task_done()

    asyncio.run(_run())
