from __future__ import annotations

from dataclasses import dataclass

from proxy.copilot.bridge import CopilotBridge, CopilotSessionHandle


@dataclass
class SessionPool:
    bridge: CopilotBridge
    active: CopilotSessionHandle | None = None

    async def ensure_active(self) -> CopilotSessionHandle:
        if self.active is None:
            self.active = await self.bridge.prewarm_session()
            self.bridge._bootstrap_session_background(self.active.session_id)
        return self.active

    async def activate(self) -> CopilotSessionHandle:
        session = await self.ensure_active()
        await self.bridge.activate_session_on_wake(session)
        return session

    async def reset_active(self) -> CopilotSessionHandle:
        self.active = await self.bridge.reset_session()
        return self.active
