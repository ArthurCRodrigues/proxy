from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
import re

from proxy.audio.assets import load_random_wake_audio
from proxy.audio.io import AudioIO
from proxy.audio.playback import PlaybackEngine
from proxy.audio.wake_vad import WakeVadEngine
from proxy.copilot.bridge import CopilotBridge
from proxy.copilot.session_pool import SessionPool
from proxy.config import Settings
from proxy.observability.logger import configure_logger, get_logger
from proxy.orchestrator.engine import Orchestrator
from proxy.orchestrator.event_bus import EventBus
from proxy.stt.deepgram_adapter import DeepgramSTTAdapter
from proxy.stt.filtering import EchoFilter, SpeechGate
from proxy.tts.elevenlabs_adapter import ElevenLabsTTSAdapter
from proxy.types import AssistantState, Event, EventType


@dataclass(frozen=True)
class _TTSCommand:
    kind: str
    text: str = ""


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

    speech_gate = SpeechGate(hold_ms=settings.stt_gate_hold_ms)
    echo_filter = EchoFilter(similarity_threshold=settings.stt_deecho_similarity_threshold)

    # Parse TTS sample rate from output format (e.g. "pcm_22050" → 22050)
    tts_sample_rate = 22050
    if settings.elevenlabs_output_format.startswith("pcm_"):
        try:
            tts_sample_rate = int(settings.elevenlabs_output_format.split("_", 1)[1])
        except ValueError:
            pass

    async def _on_tts_audio_chunk(data: bytes) -> None:
        speech_gate.block()
        await playback.push_audio(data)

    tts = ElevenLabsTTSAdapter(
        api_key=settings.elevenlabs_api_key,
        voice_id=settings.elevenlabs_voice_id,
        model_id=settings.elevenlabs_model_id,
        output_format=settings.elevenlabs_output_format,
        latency_mode=settings.elevenlabs_latency_mode,
        stability=settings.elevenlabs_stability,
        similarity_boost=settings.elevenlabs_similarity_boost,
        style=settings.elevenlabs_style,
        speed=settings.elevenlabs_speed,
        use_speaker_boost=settings.elevenlabs_use_speaker_boost,
        on_audio_chunk=_on_tts_audio_chunk,
    )

    orchestrator: Orchestrator | None = None
    cancel_commands = _parse_cancel_commands(settings.cancel_commands)
    tts_stream_active = False
    tts_stream_lock = asyncio.Lock()
    tts_command_queue: asyncio.Queue[_TTSCommand] = asyncio.Queue(
        maxsize=settings.tts_text_queue_maxsize
    )
    tts_worker_task: asyncio.Task[None] | None = None

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
        normalized = _normalize_spoken_text(text)
        if normalized in cancel_commands:
            logger.info("Voice cancel command detected: %s", text)
            asyncio.create_task(_interrupt_tts("voice_cancel"))
            asyncio.create_task(bus.publish(Event(type=EventType.CANCEL, payload={"text": text})))
            return
        if not _accept_transcript(text):
            return
        logger.debug("STT final: %s", text)
        if _is_new_session_command(text):
            logger.info("Session reset command detected from voice: %s", text)
            asyncio.create_task(_interrupt_tts("session_reset"))
            asyncio.create_task(_reset_copilot_session())
            return
        asyncio.create_task(bus.publish(Event(type=EventType.USER_FINAL, payload={"text": text})))

    async def _start_tts_stream() -> None:
        nonlocal tts_stream_active
        async with tts_stream_lock:
            if tts_stream_active:
                return
            await playback.start_stream(
                sample_rate=tts_sample_rate,
                channels=1,
                queue_maxsize=settings.tts_audio_queue_maxsize,
            )
            await tts.start_stream()
            tts_stream_active = True

    async def _finalize_tts_stream() -> None:
        nonlocal tts_stream_active
        async with tts_stream_lock:
            if not tts_stream_active:
                return
            try:
                await tts.finalize_stream()
            finally:
                await playback.end_stream()
                tts_stream_active = False

    async def _cancel_tts_stream() -> None:
        nonlocal tts_stream_active
        async with tts_stream_lock:
            await tts.cancel_stream()
            await playback.cancel()
            tts_stream_active = False

    def _drain_tts_queue() -> None:
        while True:
            try:
                command = tts_command_queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            tts_command_queue.task_done()

    def _enqueue_tts_command(command: _TTSCommand) -> None:
        try:
            tts_command_queue.put_nowait(command)
        except asyncio.QueueFull:
            logger.error("TTS command queue full; interrupting active stream")
            _drain_tts_queue()
            asyncio.create_task(_interrupt_tts("command_queue_full"))
            try:
                tts_command_queue.put_nowait(command)
            except asyncio.QueueFull:
                logger.error("TTS command dropped after queue reset: kind=%s", command.kind)

    async def _interrupt_tts(reason: str) -> None:
        logger.info("Interrupting TTS stream (%s)", reason)
        _drain_tts_queue()
        await _cancel_tts_stream()

    async def _tts_worker() -> None:
        while True:
            command = await tts_command_queue.get()
            try:
                if command.kind == "stop":
                    return
                if command.kind == "prime":
                    await _start_tts_stream()
                    continue
                if command.kind == "cancel":
                    await _cancel_tts_stream()
                    continue
                if command.kind == "finalize":
                    await _finalize_tts_stream()
                    continue
                if command.kind == "text":
                    cleaned = command.text.strip()
                    if not cleaned:
                        continue
                    # Drain any additional queued text commands into a single batch
                    parts = [cleaned]
                    while not tts_command_queue.empty():
                        try:
                            next_cmd = tts_command_queue.get_nowait()
                        except asyncio.QueueEmpty:
                            break
                        if next_cmd.kind == "text":
                            t = next_cmd.text.strip()
                            if t:
                                parts.append(t)
                            tts_command_queue.task_done()
                        else:
                            # Put non-text command back by processing it next iteration
                            await _start_tts_stream()
                            await tts.push_text("".join(parts))
                            parts = []
                            # Re-handle the non-text command
                            if next_cmd.kind == "finalize":
                                await _finalize_tts_stream()
                            elif next_cmd.kind == "cancel":
                                await _cancel_tts_stream()
                            elif next_cmd.kind == "stop":
                                tts_command_queue.task_done()
                                return
                            tts_command_queue.task_done()
                            break
                    if parts:
                        await _start_tts_stream()
                        await tts.push_text("".join(parts))
            except Exception as exc:
                logger.error("TTS command '%s' failed: %s", command.kind, exc)
                await _cancel_tts_stream()
            finally:
                tts_command_queue.task_done()

    def _on_assistant_partial(text: str) -> None:
        if not text:
            return
        echo_filter.record_assistant_text(text)
        logger.info("COPILOT_PARTIAL: %s", text)
        _enqueue_tts_command(_TTSCommand(kind="text", text=text))

    def _on_assistant_final(text: str) -> None:
        if text:
            echo_filter.record_assistant_text(text)
            logger.info("COPILOT_FINAL: %s", text)
        _enqueue_tts_command(_TTSCommand(kind="finalize"))

    stt.on_partial(_on_partial)
    stt.on_final(_on_final)

    session_pool: SessionPool | None = None

    async def _reset_copilot_session() -> None:
        if session_pool is None:
            return
        handle = await session_pool.reset_active()
        logger.info("Copilot session reset: active_session=%s", handle.session_id)

    copilot = CopilotBridge(
        event_bus=bus,
        command=settings.copilot_command,
        model=settings.copilot_model,
        allow_all=settings.copilot_allow_all,
        instructions_path=settings.copilot_instructions_path,
        on_assistant_partial=_on_assistant_partial,
        on_assistant_final=_on_assistant_final,
    )
    session_pool = SessionPool(bridge=copilot)
    tts_worker_task = asyncio.create_task(_tts_worker())

    async def on_wake() -> None:
        await session_pool.activate()
        wake_audio = load_random_wake_audio(settings.wake_sounds_dir, settings.yes_asset_path)
        speech_gate.block()
        echo_filter.record_assistant_text("yes")
        await playback.play_pcm(wake_audio)
        _enqueue_tts_command(_TTSCommand(kind="prime"))

    orchestrator = Orchestrator(bus, on_wake=on_wake, copilot_bridge=copilot)
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
        )
        await wake_vad.start()
        logger.info(
            "Proxy listening for wake phrases '%s' (input_device=%s resolved=%s)",
            settings.wake_aliases,
            settings.audio_input_device or "default",
            audio_io.resolved_input_device if audio_io.resolved_input_device is not None else "default",
        )
        await runner
    finally:
        if "wake_vad" in locals():
            await wake_vad.stop()
        if tts_worker_task is not None and not tts_worker_task.done():
            _enqueue_tts_command(_TTSCommand(kind="stop"))
            try:
                await tts_worker_task
            except asyncio.CancelledError:
                pass
        await copilot.hard_stop()
        await _cancel_tts_stream()
        await bus.publish(Event(type=EventType.STOP))
        if not runner.done():
            await asyncio.sleep(0)
            runner.cancel()


def cli() -> None:
    parser = argparse.ArgumentParser(description="Proxy voice assistant")
    parser.parse_args()
    asyncio.run(_run())


if __name__ == "__main__":
    cli()
