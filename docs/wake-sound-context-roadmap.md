# Wake Sound Context Feature Roadmap

Date: 2026-04-03

## Problem

Every wake plays a random sound from `assets/wake/`. These sounds are casual callups like "yes?", "hm?", "hey". But on the very first interaction of a session, a greeting like "Hello!" or "How are you doing?" would be more natural. Currently there's no distinction.

## Target Behavior

- First wake of the process → play a random sound from `assets/greetings/` (e.g. "Hello!", "How are you doing?").
- All subsequent wakes → play a random sound from `assets/wake/` (e.g. "yes?", "hm?", "hey").
- Both fall back to `yes_asset_path` if their directory is empty or missing.

## Implementation

### 1. Config (`proxy/config.py`)

Add one field:
- `greetings_sounds_dir: str = "assets/greetings"` backed by `PROXY_GREETINGS_SOUNDS_DIR`.

### 2. Main (`proxy/main.py`)

Add a `first_wake = True` flag in `_run()`. In `on_wake()`:
- If `first_wake`: load from `settings.greetings_sounds_dir`, set `first_wake = False`.
- Otherwise: load from `settings.wake_sounds_dir`.

### 3. Assets

No code changes to `proxy/audio/assets.py` — `load_random_wake_audio(dir, fallback)` already handles directory scanning and fallback.

Create `assets/greetings/` directory for greeting WAV files.

### 4. Env example (`.env.example`)

Add `PROXY_GREETINGS_SOUNDS_DIR=assets/greetings`.

## Files Affected

| File | Change |
|---|---|
| `proxy/config.py` | Add `greetings_sounds_dir` field + env var |
| `proxy/main.py` | Add `first_wake` flag, conditional directory in `on_wake` |
| `.env.example` | Add `PROXY_GREETINGS_SOUNDS_DIR` |
| `assets/greetings/` | New directory for greeting WAV files |
