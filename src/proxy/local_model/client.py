from __future__ import annotations

import asyncio
import json
from urllib.request import Request, urlopen

from proxy.observability.logger import get_logger

_logger = get_logger("proxy.local_model")

_FILLER_SYSTEM = (
    "You generate very short spoken acknowledgments (3-8 words) for a voice assistant. "
    "The user just asked something and the assistant is about to work on it. "
    "Respond with ONLY the filler phrase, nothing else. Be casual and natural."
)

_TOOL_SYSTEM = (
    "You generate very short casual narrations (1 sentence, under 10 words) for a voice assistant. "
    "The assistant is using a tool in the background. Describe what it's doing casually. "
    "Respond with ONLY the narration, nothing else."
)

_THOUGHT_SYSTEM = (
    "You summarize internal thoughts into one brief spoken sentence (under 15 words) for a voice assistant. "
    "Respond with ONLY the summary, nothing else."
)


class LocalModelClient:
    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "llama3.2:3b",
        timeout_s: float = 2.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout_s = timeout_s

    async def warmup(self) -> None:
        try:
            await asyncio.wait_for(
                asyncio.to_thread(self._call_ollama_raw, "Reply with OK.", "warmup", 30.0),
                timeout=35.0,
            )
            _logger.info("Local model warmed up")
        except Exception as exc:
            _logger.warning("Local model warmup failed: %s", exc)

    async def generate_latency_filler(self, user_prompt: str) -> str:
        return await self._generate(
            _FILLER_SYSTEM,
            f"User asked: {user_prompt[:100]}",
        )

    async def generate_tool_narration(self, tool_title: str) -> str:
        return await self._generate(
            _TOOL_SYSTEM,
            f"Tool being used: {tool_title}",
        )

    async def generate_thought_summary(self, thoughts: list[str]) -> str:
        return await self._generate(
            _THOUGHT_SYSTEM,
            f"Internal thoughts: {'; '.join(thoughts)}",
        )

    async def _generate(self, system: str, prompt: str) -> str:
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(self._call_ollama, system, prompt),
                timeout=self._timeout_s,
            )
        except TimeoutError:
            _logger.warning("Local model timed out")
            return ""
        except Exception as exc:
            _logger.warning("Local model error: %s", exc)
            return ""

    def _call_ollama(self, system: str, prompt: str) -> str:
        return self._call_ollama_raw(system, prompt, self._timeout_s)

    def _call_ollama_raw(self, system: str, prompt: str, timeout: float) -> str:
        payload = json.dumps({
            "model": self._model,
            "system": system,
            "prompt": prompt,
            "stream": False,
            "options": {"num_predict": 30, "temperature": 0.7},
        }).encode()
        req = Request(
            f"{self._base_url}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        resp = urlopen(req, timeout=timeout)
        body = json.loads(resp.read())
        return str(body.get("response", "")).strip().strip('"')
