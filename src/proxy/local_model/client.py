from __future__ import annotations

import asyncio
import json
from urllib.request import Request, urlopen

from proxy.observability.logger import get_logger

_logger = get_logger("proxy.local_model")

_PERSONA = (
    "You speak like a chill, friendly colleague — casual, warm, a bit playful. "
    "Use natural spoken language like 'hold on', 'yo', 'alright', 'let me', 'gimme a sec'. "
    "Never sound robotic or formal. Never say 'analyzing' or 'processing'. "
)

_FILLER_SYSTEM = (
    f"{_PERSONA}"
    "The user just gave you a coding task. "
    "Generate a short spoken acknowledgment (5-12 words) that shows you understood what they asked. "
    "Reference the specific topic from their request. "
    "CRITICAL: Do NOT answer the question. Do NOT provide any information. "
    "You are ONLY acknowledging that you heard them and are about to start working. "
    "Respond with ONLY the acknowledgment, nothing else. Examples: "
    "'Hold on, let me dig into the auth flow.', "
    "'Yo, checking those migrations right now.', "
    "'Alright, let me pull up those test failures.'"
)

_THOUGHT_SYSTEM = (
    f"{_PERSONA}"
    "Summarize a coding assistant's internal status into one brief spoken sentence (under 12 words). "
    "The assistant is working on a coding task. These are its internal thoughts. "
    "Respond with ONLY the summary, nothing else. Be accurate to what the thoughts say."
)

_TOOL_SUMMARY_SYSTEM = (
    f"{_PERSONA}"
    "Summarize a list of actions a coding assistant just performed into one brief spoken sentence (under 15 words). "
    "Be factual — only describe what's in the list. Do NOT invent details. "
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
                asyncio.to_thread(self._call_ollama_raw, "Reply with OK.", "warmup", 60.0),
                timeout=65.0,
            )
            _logger.info("Local model warmed up")
        except Exception as exc:
            _logger.warning("Local model warmup failed: %s", exc)

    async def generate_latency_filler(self, user_prompt: str) -> str:
        return await self._generate(
            _FILLER_SYSTEM,
            f"User said: \"{user_prompt[:200]}\"",
        )

    async def generate_thought_summary(self, thoughts: list[str]) -> str:
        return await self._generate(
            _THOUGHT_SYSTEM,
            f"Internal thoughts: {'; '.join(thoughts)}",
        )

    async def generate_tool_summary(self, descriptions: list[str]) -> str:
        return await self._generate(
            _TOOL_SUMMARY_SYSTEM,
            f"Actions performed:\n- " + "\n- ".join(descriptions),
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
