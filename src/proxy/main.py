from __future__ import annotations

import argparse
import asyncio
import re

from proxy.audio.assets import choose_wake_sounds_dir, load_random_wake_audio
from proxy.audio.io import AudioIO, list_input_devices
from proxy.audio.playback import PlaybackEngine
from proxy.audio.wake_vad import WakeVadEngine
from proxy.copilot.bridge import CopilotBridge
from proxy.copilot.session_pool import SessionPool
from proxy.config import Settings
from proxy.observability.logger import configure_logger, get_logger
from proxy.observability.timing import TurnTimer
from proxy.orchestrator.engine import Orchestrator
from proxy.orchestrator.event_bus import EventBus
from proxy.stt.deepgram_adapter import DeepgramSTTAdapter
from proxy.stt.filtering import EchoFilter, SpeechGate
from proxy.tts.chunking import append_partial, consume_speakable_segments, merge_final, split_speakable_segments
from proxy.tts.elevenlabs_adapter import ElevenLabsTTSAdapter
from proxy.types import AssistantState, Event, EventType


def _normalize_spoken_text(text: str) -> str:
    cleaned = re.sub(r"[^a-z0-9\s]", " ", text.lower())
    return " ".join(cleaned.split())


def _is_new_session_command(text: str) -> bool:
    normalized = _normalize_spoken_text(text)
    commands = (
        "start new session",
        "new session",
        "reset session",
        "fresh session",
    )
    return any(cmd in normalized for cmd in commands)


def _parse_cancel_commands(raw: str) -> tuple[str, ...]:
    return tuple(_normalize_spoken_text(part) for part in raw.split(",") if part.strip())


async def _run() -> None:
    settings = Settings.from_env()
    configure_logger(settings.log_level, settings.log_debug_modules)
    logger = get_logger("proxy.main")
    logger.info("Starting Proxy bootstrap")

    bus = EventBus(maxsize=settings.queue_maxsize)
    playback = PlaybackEngine()
    audio_io = AudioIO(
        sample_rate=settings.audio_sample_rate,
        channels=settings.audio_channels,
        chunk_ms=settings.audio_chunk_ms,
        queue_maxsize=settings.audio_input_queue_maxsize,
        input_device=settings.audio_input_device,
    )

    stt = DeepgramSTTAdapter(
        api_key=settings.deepgram_api_key,
        sample_rate=settings.audio_sample_rate,
        model=settings.deepgram_model,
        language=settings.deepgram_language,
        endpointing_enabled=settings.deepgram_endpointing_enabled,
        endpointing_ms=settings.deepgram_endpointing_ms,
        utterance_end_ms=settings.deepgram_utterance_end_ms,
        punctuate=settings.deepgram_punctuate,
        smart_format=settings.deepgram_smart_format,
        keyterms=settings.deepgram_keyterms,
        interim_results=settings.deepgram_interim_results,
        reconnect_max_attempts=settings.deepgram_reconnect_max_attempts,
        reconnect_base_delay_ms=settings.deepgram_reconnect_base_delay_ms,
    )
    tts = ElevenLabsTTSAdapter(
        api_key=settings.elevenlabs_api_key,
        voice_id=settings.elevenlabs_voice_id,
        model_id=settings.elevenlabs_model_id,
        output_format=settings.elevenlabs_output_format,
        fallback_output_formats=settings.elevenlabs_fallback_output_formats,
        stability=settings.elevenlabs_stability,
        similarity_boost=settings.elevenlabs_similarity_boost,
        style=settings.elevenlabs_style,
        speed=settings.elevenlabs_speed,
        use_speaker_boost=settings.elevenlabs_use_speaker_boost,
    )

    speech_gate = SpeechGate(hold_ms=settings.stt_gate_hold_ms)
    echo_filter = EchoFilter(similarity_threshold=settings.stt_deecho_similarity_threshold)
    orchestrator: Orchestrator | None = None
    tts_queue: asyncio.Queue[tuple[str | None, str | None, bool]] = asyncio.Queue(maxsize=64)
    tts_task: asyncio.Task[None] | None = None
    tts_text_buffer = ""
    tts_partial_seen_since_final = False
    cancel_commands = _parse_cancel_commands(settings.cancel_commands)
    first_wake = True
    turn_timer: TurnTimer | None = None

    def _allow_stt_audio_forward() -> bool:
        if orchestrator is None:
            return False
        if orchestrator.context.state != AssistantState.LISTENING:
            return False
        if settings.stt_gate_enabled and not speech_gate.allow():
            return False
        return True

    def _accept_transcript(text: str) -> bool:
        if orchestrator is not None and orchestrator.context.state != AssistantState.LISTENING:
            logger.debug(
                "Dropped STT outside LISTENING state (%s): %s",
                orchestrator.context.state,
                text,
            )
            return False
        if settings.stt_gate_enabled and not speech_gate.allow():
            logger.debug("Dropped STT due to speech gate: %s", text)
            return False
        if settings.stt_deecho_enabled and echo_filter.is_echo(text):
            logger.debug("Dropped STT due to de-echo match: %s", text)
            return False
        return True

    def _on_partial(text: str) -> None:
        if not _accept_transcript(text):
            return
        logger.debug("STT partial: %s", text)
        asyncio.create_task(bus.publish(Event(type=EventType.USER_PARTIAL, payload={"text": text})))

    def _on_final(text: str) -> None:
        if not _accept_transcript(text):
            return
        logger.debug("STT final: %s", text)
        normalized = _normalize_spoken_text(text)
        if normalized in cancel_commands:
            logger.info("Voice cancel command detected: %s", text)
            asyncio.create_task(bus.publish(Event(type=EventType.CANCEL, payload={"text": text})))
            return
        if _is_new_session_command(text):
            logger.info("Session reset command detected from voice: %s", text)
            asyncio.create_task(_reset_copilot_session())
            return
        if turn_timer is not None:
            turn_timer.stamp("user_final")
        asyncio.create_task(bus.publish(Event(type=EventType.USER_FINAL, payload={"text": text})))

    def _on_assistant_partial(text: str, turn_id: str | None) -> None:
        nonlocal tts_text_buffer, tts_partial_seen_since_final
        if text:
            if turn_timer is not None and "first_partial" not in turn_timer._stamps:
                turn_timer.stamp("first_partial")
            echo_filter.record_assistant_text(text)
            logger.info("COPILOT_PARTIAL: %s", text)
            if not settings.tts_speak_partials:
                return
            tts_partial_seen_since_final = True
            tts_text_buffer = append_partial(tts_text_buffer, text)
            segments, tts_text_buffer, _consumed = consume_speakable_segments(
                tts_text_buffer,
                force=False,
                min_chars=settings.tts_partial_min_chars,
                force_flush_chars=settings.tts_partial_force_flush_chars,
            )
            for segment in segments:
                try:
                    tts_queue.put_nowait((segment, turn_id, False))
                except asyncio.QueueFull:
                    logger.debug("TTS queue full; dropping partial chunk")

    def _on_assistant_final(text: str, turn_id: str | None) -> None:
        nonlocal tts_text_buffer, tts_partial_seen_since_final
        if text:
            echo_filter.record_assistant_text(text)
            logger.info("COPILOT_FINAL: %s", text)
            if settings.tts_speak_partials and tts_partial_seen_since_final:
                segments, tts_text_buffer = split_speakable_segments(
                    tts_text_buffer,
                    force=True,
                    force_flush_chars=settings.tts_partial_force_flush_chars,
                )
            else:
                tts_text_buffer = merge_final(tts_text_buffer, text)
                segments, tts_text_buffer = split_speakable_segments(
                    tts_text_buffer,
                    force=True,
                    force_flush_chars=settings.tts_partial_force_flush_chars,
                )
            tts_partial_seen_since_final = False
            for segment in segments:
                try:
                    tts_queue.put_nowait((segment, turn_id, False))
                except asyncio.QueueFull:
                    logger.debug("TTS queue full; dropping final chunk")
        tts_partial_seen_since_final = False
        # Mark turn completion so state can return to IDLE only after playback has actually drained.
        asyncio.create_task(tts_queue.put((None, turn_id, True)))
        if turn_timer is not None:
            turn_timer.stamp("assistant_final")
            turn_timer.log_summary()

    async def _tts_loop() -> None:
        while True:
            text, turn_id, turn_done = await tts_queue.get()
            try:
                if turn_done:
                    await bus.publish(
                        Event(
                            type=EventType.ASSISTANT_AUDIO_DONE,
                            turn_id=turn_id,
                        )
                    )
                    continue
                cleaned = (text or "").strip()
                if not cleaned:
                    continue
                logger.info("TTS_OUTBOUND_CHUNK: %s", cleaned)
                if turn_timer is not None and "first_tts" not in turn_timer._stamps:
                    turn_timer.stamp("first_tts")
                speech_gate.block()
                echo_filter.record_assistant_text(cleaned)
                try:
                    audio = await tts.synthesize_text(cleaned)
                    if audio.data:
                        await playback.play_pcm(audio)
                except Exception as exc:
                    logger.error("TTS synthesis/playback error: %s", exc)
            finally:
                tts_queue.task_done()

    stt.on_partial(_on_partial)
    stt.on_final(_on_final)

    session_pool: SessionPool | None = None

    async def _reset_copilot_session() -> None:
        if session_pool is None:
            return
        handle = await session_pool.reset_active()
        logger.info("Copilot session reset: active_session=%s", handle.session_id)

    def _on_narration(text: str) -> None:
        if text:
            logger.info("NARRATION: %s", text)
            echo_filter.record_assistant_text(text)
            try:
                tts_queue.put_nowait((text, None, False))
            except asyncio.QueueFull:
                logger.debug("TTS queue full; dropping narration")

    copilot = CopilotBridge(
        event_bus=bus,
        command=settings.copilot_command,
        model=settings.copilot_model,
        allow_all=settings.copilot_allow_all,
        instructions_path=settings.copilot_instructions_path,
        on_assistant_partial=_on_assistant_partial,
        on_assistant_final=_on_assistant_final,
        on_narration=_on_narration,
    )
    session_pool = SessionPool(bridge=copilot)
    tts_task = asyncio.create_task(_tts_loop())

    async def on_wake() -> None:
        nonlocal first_wake, turn_timer
        turn_timer = TurnTimer()
        turn_timer.stamp("wake")
        await session_pool.activate()
        wake_sounds_dir = choose_wake_sounds_dir(
            first_wake=first_wake,
            greetings_sounds_dir=settings.greetings_sounds_dir,
            wake_sounds_dir=settings.wake_sounds_dir,
        )
        first_wake = False
        wake_audio = load_random_wake_audio(wake_sounds_dir, settings.yes_asset_path)
        speech_gate.block()
        echo_filter.record_assistant_text("yes")
        await playback.play_pcm(wake_audio)
        turn_timer.stamp("ready")

    async def on_interrupt() -> None:
        nonlocal tts_text_buffer, tts_partial_seen_since_final
        logger.info("Interrupt: cancelling copilot and TTS")
        await copilot.hard_stop_turn()
        await playback.cancel()
        tts_text_buffer = ""
        tts_partial_seen_since_final = False
        # Drain TTS queue
        while not tts_queue.empty():
            try:
                tts_queue.get_nowait()
                tts_queue.task_done()
            except asyncio.QueueEmpty:
                break

    orchestrator = Orchestrator(bus, on_wake=on_wake, copilot_bridge=copilot, on_interrupt=on_interrupt)
    orchestrator.set_listening_timeout(settings.listening_timeout_ms)
    runner = asyncio.create_task(orchestrator.run())

    try:
        await session_pool.ensure_active()
        logger.info("Copilot session created and bootstrapping")
        wake_vad = WakeVadEngine(
            event_bus=bus,
            audio_io=audio_io,
            sample_rate=settings.audio_sample_rate,
            wake_phrase=settings.wake_phrase,
            wake_aliases=settings.wake_aliases,
            vosk_model_path=settings.vosk_model_path,
            debug_transcripts=settings.wake_debug_transcripts,
            wake_enabled=lambda: orchestrator.context.state == AssistantState.IDLE,
            wake_retrigger_cooldown_ms=settings.wake_retrigger_cooldown_ms,
            wake_rearm_guard_ms=settings.wake_rearm_guard_ms,
            wake_match_partial=settings.wake_match_partial,
            stt_adapter=stt,
            stt_gate_allow=_allow_stt_audio_forward,
            stopword_phrases=[p.strip() for p in settings.stopword_aliases.split(",") if p.strip()],
            stopword_enabled=lambda: orchestrator.context.state in (AssistantState.THINKING, AssistantState.SPEAKING),
            stopword_cooldown_ms=settings.stopword_cooldown_ms,
        )
        await wake_vad.start()
        logger.info(
            "Proxy listening for wake phrases '%s' (input_device=%s resolved=%s)",
            settings.wake_aliases,
            settings.audio_input_device or "default",
            audio_io.resolved_input_device if audio_io.resolved_input_device is not None else "default",
        )
        logger.debug(
            "Wake diagnostics enabled=%s retrigger_cooldown_ms=%s",
            settings.wake_debug_transcripts,
            settings.wake_retrigger_cooldown_ms,
        )
        await runner
    finally:
        if "wake_vad" in locals():
            await wake_vad.stop()
        await copilot.hard_stop()
        await tts.cancel()
        if tts_task is not None and not tts_task.done():
            tts_task.cancel()
            try:
                await tts_task
            except asyncio.CancelledError:
                pass
        await playback.cancel()
        await bus.publish(Event(type=EventType.STOP))
        if not runner.done():
            await asyncio.sleep(0)
            runner.cancel()


def _install_service() -> None:
    import subprocess
    import sys
    from pathlib import Path

    project_dir = Path(__file__).resolve().parents[2]
    python = sys.executable
    service_dir = Path.home() / ".config" / "systemd" / "user"
    service_file = service_dir / "proxy.service"

    service_dir.mkdir(parents=True, exist_ok=True)
    service_file.write_text(
        f"[Unit]\n"
        f"Description=Proxy — voice layer for your coding agent\n"
        f"After=network.target sound.target\n\n"
        f"[Service]\n"
        f"Type=simple\n"
        f"WorkingDirectory={project_dir}\n"
        f"Environment=PYTHONPATH={project_dir / 'src'}\n"
        f"ExecStart={python} -m proxy.main\n"
        f"Restart=on-failure\n"
        f"RestartSec=5\n\n"
        f"[Install]\n"
        f"WantedBy=default.target\n"
    )

    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "--user", "enable", "proxy.service"], check=True)
    subprocess.run(["systemctl", "--user", "start", "proxy.service"], check=True)

    print("Proxy installed as a systemd user service.")
    print("  Status:  systemctl --user status proxy")
    print("  Logs:    journalctl --user -u proxy -f")
    print("  Stop:    systemctl --user stop proxy")
    print("  Disable: systemctl --user disable proxy")


def _init() -> None:
    import shutil
    import subprocess
    import urllib.request
    import zipfile
    from io import BytesIO
    from pathlib import Path

    project_dir = Path(__file__).resolve().parents[2]
    env_file = project_dir / ".env"
    env_example = project_dir / ".env.example"
    vosk_dir = project_dir / "assets" / "models" / "vosk-model-small-en-us-0.15"

    print("\nProxy Setup")
    print("=" * 40)

    # 1. PortAudio
    print("\n[1/5] Checking PortAudio...")
    try:
        import sounddevice  # noqa: F401
        print("      ✓ found")
    except (ImportError, OSError):
        print("      ✗ not found")
        print("      Install it: brew install portaudio (macOS) or apt install portaudio19-dev (Linux)")
        return

    # 2. Vosk model
    print("\n[2/5] Checking Vosk model...")
    if vosk_dir.exists():
        print(f"      ✓ found at {vosk_dir}")
    else:
        answer = input("      Not found. Download now? [Y/n] ").strip().lower()
        if answer in ("", "y", "yes"):
            url = "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip"
            print(f"      Downloading (~40MB)...")
            try:
                data = urllib.request.urlopen(url).read()
                models_dir = vosk_dir.parent
                models_dir.mkdir(parents=True, exist_ok=True)
                with zipfile.ZipFile(BytesIO(data)) as zf:
                    zf.extractall(models_dir)
                print("      ✓ downloaded")
            except Exception as exc:
                print(f"      ✗ download failed: {exc}")
                return
        else:
            print("      Skipped. Set PROXY_VOSK_MODEL_PATH in .env to your model path.")

    # 3. Deepgram
    print("\n[3/5] Deepgram API key (speech-to-text)")
    print("      Get one at https://console.deepgram.com")
    deepgram_key = input("      Key: ").strip()
    if not deepgram_key:
        print("      ✗ skipped")
    else:
        print("      ✓ saved")

    # 4. ElevenLabs
    print("\n[4/5] ElevenLabs (text-to-speech)")
    print("      Get one at https://elevenlabs.io/api")
    elevenlabs_key = input("      API Key: ").strip()
    elevenlabs_voice = input("      Voice ID: ").strip()
    if not elevenlabs_key or not elevenlabs_voice:
        print("      ✗ skipped")
    else:
        print("      ✓ saved")

    # 5. Copilot
    print("\n[5/5] Checking Copilot CLI...")
    if shutil.which("copilot"):
        print("      ✓ copilot found")
    else:
        print("      ✗ copilot not found in PATH")
        print("      Install: https://docs.github.com/en/copilot/github-copilot-in-the-cli")

    # Write .env
    print()
    if env_file.exists():
        overwrite = input(".env already exists. Overwrite? [y/N] ").strip().lower()
        if overwrite not in ("y", "yes"):
            print("Keeping existing .env")
        else:
            _write_env(env_file, env_example, deepgram_key, elevenlabs_key, elevenlabs_voice)
    else:
        _write_env(env_file, env_example, deepgram_key, elevenlabs_key, elevenlabs_voice)

    # Optional: startup service
    print()
    startup = input("Start on login? (Linux systemd) [y/N] ").strip().lower()
    if startup in ("y", "yes"):
        try:
            _install_service()
        except Exception as exc:
            print(f"Service install failed: {exc}")

    print("\nReady! Run `proxy` to start.\n")


def _write_env(
    env_file: "Path",
    env_example: "Path",
    deepgram_key: str,
    elevenlabs_key: str,
    elevenlabs_voice: str,
) -> None:
    from pathlib import Path

    if env_example.exists():
        content = env_example.read_text(encoding="utf-8")
    else:
        content = ""

    replacements = {
        "DEEPGRAM_API_KEY=": f"DEEPGRAM_API_KEY={deepgram_key}",
        "ELEVENLABS_API_KEY=": f"ELEVENLABS_API_KEY={elevenlabs_key}",
        "ELEVENLABS_VOICE_ID=": f"ELEVENLABS_VOICE_ID={elevenlabs_voice}",
    }

    lines = content.splitlines()
    result = []
    for line in lines:
        replaced = False
        for prefix, replacement in replacements.items():
            if line.strip().startswith(prefix) and line.strip() == prefix:
                result.append(replacement)
                replaced = True
                break
        if not replaced:
            result.append(line)

    env_file.write_text("\n".join(result) + "\n", encoding="utf-8")
    print(f"      Wrote {env_file}")


def _devices() -> None:
    try:
        devices = list_input_devices()
    except RuntimeError as exc:
        print(f"Unable to list input devices: {exc}")
        return

    if not devices:
        print("No audio input devices found.")
        return

    idx_width = max(len("INDEX"), max(len(str(idx)) for idx, _, _ in devices))
    rate_width = max(len("RATE"), max(len(str(rate)) for _, _, rate in devices))
    print(f"{'INDEX':>{idx_width}}  {'RATE':>{rate_width}}  NAME")
    for idx, name, sample_rate in devices:
        print(f"{idx:>{idx_width}}  {sample_rate:>{rate_width}}  {name}")


def _service_cmd(*args: str) -> None:
    import subprocess
    try:
        subprocess.run(["systemctl", "--user", *args, "proxy.service"], check=True)
    except FileNotFoundError:
        print("Error: systemctl not found. This command requires Linux with systemd.")
    except subprocess.CalledProcessError as exc:
        print(f"Error: systemctl exited with code {exc.returncode}")


def _service_logs() -> None:
    import subprocess
    try:
        subprocess.run(["journalctl", "--user", "-u", "proxy", "-f"], check=True)
    except FileNotFoundError:
        print("Error: journalctl not found. This command requires Linux with systemd.")
    except KeyboardInterrupt:
        pass


def _is_service_active() -> bool:
    import subprocess
    try:
        result = subprocess.run(
            ["systemctl", "--user", "is-active", "proxy.service"],
            capture_output=True, text=True,
        )
        return result.stdout.strip() == "active"
    except FileNotFoundError:
        return False


def cli() -> None:
    parser = argparse.ArgumentParser(description="Proxy voice assistant")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("init", help="Guided first-time setup")
    sub.add_parser("setup", help="Install Proxy as a startup service (Linux)")
    sub.add_parser("stop", help="Stop the Proxy background service")
    sub.add_parser("restart", help="Restart the Proxy background service")
    sub.add_parser("logs", help="Follow logs from the Proxy background service")
    sub.add_parser("devices", help="List available audio input devices")
    args = parser.parse_args()

    if args.command == "init":
        _init()
    elif args.command == "setup":
        _install_service()
    elif args.command == "stop":
        _service_cmd("stop")
    elif args.command == "restart":
        _service_cmd("restart")
    elif args.command == "logs":
        _service_logs()
    elif args.command == "devices":
        _devices()
    else:
        if _is_service_active():
            print("Proxy is already running as a background service.")
            print("  Logs:    proxy logs")
            print("  Restart: proxy restart")
            print("  Stop:    proxy stop")
        else:
            asyncio.run(_run())


if __name__ == "__main__":
    cli()
