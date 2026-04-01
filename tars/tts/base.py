from __future__ import annotations

from abc import ABC, abstractmethod

from tars.audio.assets import PcmAudio


class TTSAdapter(ABC):
    @abstractmethod
    async def synthesize_text(self, text: str) -> PcmAudio:
        raise NotImplementedError

    @abstractmethod
    async def cancel(self) -> None:
        raise NotImplementedError
