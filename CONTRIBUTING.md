# Contributing to Proxy

Thanks for your interest in contributing. Here's how to get started.

## Setup

```bash
git clone https://github.com/ArthurCRodrigues/proxy.git
cd proxy
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

You'll also need PortAudio installed (`brew install portaudio` on macOS).

## Running tests

```bash
pytest -q
```

Tests don't require API keys or external services — they test internal logic only.

## Code style

- Python 3.11+ with `from __future__ import annotations`
- No runtime type checking libraries — just standard type hints
- Keep modules small and focused
- No base classes unless there are multiple implementations

## Where to contribute

See the [roadmap](docs/ROADMAP.md) for planned work. High-impact areas:

- **Agent backends** — Add support for coding agents beyond Copilot (Claude Code, Aider, Continue)
- **STT/TTS providers** — Alternative speech engines for different cost/latency/privacy tradeoffs
- **Language support** — Wake word models and STT configs for non-English languages
- **Latency optimization** — Profiling, benchmarking, reducing time-to-first-audio

## Pull requests

- One feature or fix per PR
- Include tests for new behavior
- Don't modify existing tests unless the behavior they test has changed
- Keep commits focused and messages clear
