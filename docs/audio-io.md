# Audio I/O

Proxy captures microphone input and plays back synthesized speech through the system's audio devices using `sounddevice`, a Python binding for PortAudio.

## Microphone capture (AudioIO)

`AudioIO` opens a `RawInputStream` that captures 16-bit PCM audio from the microphone in fixed-size chunks.

### Chunk sizing

Audio is captured in chunks defined by `PROXY_AUDIO_CHUNK_MS` (default 20ms). At the default sample rate of 16000 Hz, this produces 320 frames per chunk (640 bytes of int16 mono audio). Small chunks keep latency low — the wake engine and VAD process each chunk as it arrives.

The frame count per chunk is computed as:
```
frames = sample_rate * chunk_ms / 1000
```

### Device selection

By default, Proxy uses the system's default input device. To use a specific device, set `PROXY_AUDIO_INPUT_DEVICE` to either:
- A device index (integer).
- A device name or substring (case-sensitive). The resolver tries exact match first, then substring match against all available input devices.

If the specified device can't be found, startup fails with a `ValueError` listing all available devices.

### Sample rate fallback

If the configured sample rate (default 16000 Hz) isn't supported by the selected device, `AudioIO` falls back to the device's default sample rate. A warning is logged, and the actual sample rate is propagated to all downstream consumers (Vosk recognizer, Deepgram connection).

### Backpressure

Audio chunks are placed on an internal `asyncio.Queue` with a configurable max size (`PROXY_AUDIO_INPUT_QUEUE_MAXSIZE`, default 128). If the queue fills up (the consumer isn't keeping up), the oldest chunk is dropped to make room for the new one. This ensures the audio stream stays current rather than building up latency.

The callback from sounddevice runs in a separate thread. It uses `loop.call_soon_threadsafe` to enqueue chunks into the async queue.

## Playback (PlaybackEngine)

`PlaybackEngine` plays `PcmAudio` objects through the system's default output device using a `RawOutputStream`.

Audio is written in 20ms chunks. Between each chunk write, the engine yields to the event loop with `asyncio.sleep(0)`. This cooperative scheduling ensures that other async tasks (event processing, STT streaming, etc.) aren't starved during long playback.

Only one playback can be active at a time. Calling `play_pcm` while audio is already playing cancels the previous playback first.

## Wake sounds (assets)

Proxy plays a random acknowledgment sound when the wake word is detected. These sounds are WAV files stored in the `assets/wake/` directory (configurable via `PROXY_WAKE_SOUNDS_DIR`).

On each wake event:
1. `list_wake_wavs` recursively scans the directory for `.wav` files.
2. `choose_wake_sound` picks one at random.
3. If no WAV files are found, it falls back to `PROXY_YES_ASSET_PATH` (default `assets/yes.wav`).
4. The WAV is loaded as `PcmAudio` (must be PCM16 format).

All asset paths are resolved relative to the project root. Absolute paths are used as-is.

## Configuration

| Setting | Default | Purpose |
|---|---|---|
| `PROXY_AUDIO_SAMPLE_RATE` | `16000` | Capture sample rate in Hz |
| `PROXY_AUDIO_CHANNELS` | `1` | Number of capture channels (mono) |
| `PROXY_AUDIO_CHUNK_MS` | `20` | Capture chunk duration in milliseconds |
| `PROXY_AUDIO_INPUT_QUEUE_MAXSIZE` | `128` | Max buffered chunks before dropping |
| `PROXY_AUDIO_INPUT_DEVICE` | (default device) | Input device index or name |
| `PROXY_WAKE_SOUNDS_DIR` | `assets/wake` | Directory of wake acknowledgment WAVs |
| `PROXY_YES_ASSET_PATH` | `assets/yes.wav` | Fallback wake sound |
