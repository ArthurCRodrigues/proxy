from __future__ import annotations

from dataclasses import dataclass

from proxy.copilot.bridge import CopilotBridge, CopilotSessionHandle


@dataclass
class SessionPool:
    bridge: CopilotBridge
    active: CopilotSessionHandle | None = None
    standby: CopilotSessionHandle | None = None

    async def ensure_standby(self) -> CopilotSessionHandle:
        if self.standby is None:
            self.standby = await self.bridge.prewarm_session()
        return self.standby

    async def activate_standby(self) -> CopilotSessionHandle:
        if self.active is None:
            standby = await self.ensure_standby()
            self.active = await self.bridge.activate_session_on_wake(standby)
            self.standby = None
        else:
            self.active = await self.bridge.activate_session_on_wake(self.active)
        return self.active

    async def rollover(self) -> None:
        self.standby = await self.bridge.prewarm_session()

    async def reset_active(self) -> CopilotSessionHandle:
        self.active = await self.bridge.reset_session()
        self.standby = None
        return self.active
