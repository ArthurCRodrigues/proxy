from __future__ import annotations

import argparse
import asyncio
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
    configure_logger(settings.log_level)
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
    tts_queue: asyncio.Queue[str] = asyncio.Queue(maxsize=64)
    tts_task: asyncio.Task[None] | None = None
    tts_text_buffer = ""
    tts_partial_seen_since_final = False
    cancel_commands = _parse_cancel_commands(settings.cancel_commands)

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
        asyncio.create_task(bus.publish(Event(type=EventType.USER_FINAL, payload={"text": text})))

    def _on_assistant_partial(text: str) -> None:
        nonlocal tts_text_buffer, tts_partial_seen_since_final
        if text:
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
                    tts_queue.put_nowait(segment)
                except asyncio.QueueFull:
                    logger.debug("TTS queue full; dropping partial chunk")

    def _on_assistant_final(text: str) -> None:
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
                    tts_queue.put_nowait(segment)
                except asyncio.QueueFull:
                    logger.debug("TTS queue full; dropping final chunk")

    async def _tts_loop() -> None:
        while True:
            text = await tts_queue.get()
            try:
                cleaned = text.strip()
                if not cleaned:
                    continue
                logger.info("TTS_OUTBOUND_CHUNK: %s", cleaned)
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
    tts_task = asyncio.create_task(_tts_loop())

    async def on_wake() -> None:
        await session_pool.activate_standby()
        wake_audio = load_random_wake_audio(settings.wake_sounds_dir, settings.yes_asset_path)
        speech_gate.block()
        echo_filter.record_assistant_text("yes")
        await playback.play_pcm(wake_audio)
        await session_pool.rollover()

    orchestrator = Orchestrator(bus, on_wake=on_wake, copilot_bridge=copilot)
    orchestrator.set_listening_timeout(settings.listening_timeout_ms)
    runner = asyncio.create_task(orchestrator.run())

    try:
        await session_pool.ensure_standby()
        logger.info("Copilot standby session prewarmed and bootstrapping")
        wake_vad = WakeVadEngine(
            event_bus=bus,
            audio_io=audio_io,
            sample_rate=settings.audio_sample_rate,
            wake_phrase=settings.wake_phrase,
            wake_aliases=settings.wake_aliases,
            vosk_model_path=settings.vosk_model_path,
            vad_start_rms=settings.vad_start_rms,
            vad_end_rms=settings.vad_end_rms,
            vad_end_silence_ms=settings.vad_end_silence_ms,
            debug_transcripts=settings.wake_debug_transcripts,
            debug_rms=settings.wake_debug_rms,
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


def cli() -> None:
    parser = argparse.ArgumentParser(description="Proxy voice assistant")
    parser.parse_args()
    asyncio.run(_run())


if __name__ == "__main__":
    cli()
