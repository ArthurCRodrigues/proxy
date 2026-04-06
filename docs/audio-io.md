# Audio I/O

Proxy captures microphone input and plays back audio using `sounddevice` (PortAudio binding).

## Microphone capture (AudioIO)

Opens a `RawInputStream` capturing 16-bit PCM mono audio in 20ms chunks (320 frames at 16kHz). Chunks are placed on an async queue. If the queue fills up, the oldest chunk is dropped to keep audio current.

The device can be selected by index or name substring via `PROXY_AUDIO_INPUT_DEVICE`. Run `proxy devices` to list available input devices (index, name, and sample rate). If the configured sample rate isn't supported, AudioIO falls back to the device's default rate and propagates it to all downstream consumers.

## Playback (PlaybackEngine)

Plays `PcmAudio` objects through the default output device via `RawOutputStream`. Audio is written in 20ms chunks with `asyncio.sleep(0)` between writes for cooperative scheduling. Only one playback runs at a time — starting a new one cancels the previous.

## Wake sounds

On each wake event, a random WAV is loaded from a local directory:
- First wake of the process: `assets/greetings/` (e.g. "Hello!")
- Subsequent wakes: `assets/wake/` (e.g. "Yes?", "Hm?")
- Fallback if directory is empty: `assets/yes.wav`
