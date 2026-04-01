from __future__ import annotations

import asyncio
from pathlib import Path

from tars.copilot.bridge import CopilotBridge
from tars.orchestrator.event_bus import EventBus
from tars.types import EventType


def test_bridge_prewarm_and_rollover() -> None:
    async def _run() -> None:
        bus = EventBus()
        bridge = CopilotBridge(event_bus=bus)
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
    assert "Output contract for assistant.message final:" in wrapped
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
