from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable


class STTAdapter(ABC):
    @abstractmethod
    async def start_stream(self, sample_rate: int | None = None) -> None:
        raise NotImplementedError

    @abstractmethod
    async def push_audio(self, data: bytes) -> None:
        raise NotImplementedError

    @abstractmethod
    async def end_utterance(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def cancel(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def on_partial(self, cb: Callable[[str], None]) -> None:
        raise NotImplementedError

    @abstractmethod
    def on_final(self, cb: Callable[[str], None]) -> None:
        raise NotImplementedError

    @abstractmethod
    def ready(self) -> bool:
        raise NotImplementedError
