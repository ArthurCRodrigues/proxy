from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _load_dotenv(dotenv_path: str = ".env") -> None:
    path = Path(dotenv_path)
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def _parse_csv(value: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in value.split(",") if part.strip())


def _default_copilot_instructions_path() -> str:
    return str(Path(__file__).resolve().parents[2] / "instructions.md")


@dataclass(frozen=True)
class Settings:
    deepgram_api_key: str
    elevenlabs_api_key: str
    elevenlabs_voice_id: str
    elevenlabs_model_id: str = "eleven_multilingual_v2"
    elevenlabs_output_format: str = "pcm_22050"
    elevenlabs_fallback_output_formats: tuple[str, ...] = ("wav_22050",)
    elevenlabs_stability: float = 0.45
    elevenlabs_similarity_boost: float = 0.85
    elevenlabs_style: float = 0.25
    elevenlabs_speed: float = 0.95
    elevenlabs_use_speaker_boost: bool = True
    log_level: str = "INFO"
    log_debug_modules: str = ""
    queue_maxsize: int = 256
    audio_sample_rate: int = 16000
    audio_channels: int = 1
    audio_chunk_ms: int = 20
    audio_input_queue_maxsize: int = 128
    audio_input_device: str = ""
    yes_asset_path: str = "assets/yes.wav"
    greetings_sounds_dir: str = "assets/greetings"
    wake_sounds_dir: str = "assets/wake"
    wake_phrase: str = "proxy"
    wake_aliases: str = "proxy,roxy,rocky"
    vosk_model_path: str = "assets/models/vosk-model-small-en-us-0.15"
    wake_debug_transcripts: bool = False
    wake_retrigger_cooldown_ms: int = 1500
    wake_rearm_guard_ms: int = 1200
    wake_match_partial: bool = False
    stopword_phrase: str = "stop"
    stopword_aliases: str = "stop,shut up"
    stopword_cooldown_ms: int = 1500
    deepgram_model: str = "nova-3"
    deepgram_language: str = "en-US"
    deepgram_endpointing_enabled: bool = True
    deepgram_endpointing_ms: int = 700
    deepgram_utterance_end_ms: int = 3500
    deepgram_punctuate: bool = True
    deepgram_smart_format: bool = True
    deepgram_keyterms: tuple[str, ...] = ()
    deepgram_interim_results: bool = True
    deepgram_reconnect_max_attempts: int = 3
    deepgram_reconnect_base_delay_ms: int = 200
    stt_gate_enabled: bool = True
    stt_gate_hold_ms: int = 900
    stt_deecho_enabled: bool = True
    stt_deecho_similarity_threshold: float = 0.78
    listening_timeout_ms: int = 10000
    cancel_commands: str = "nevermind,never mind,quit"
    copilot_command: str = "copilot"
    copilot_model: str = ""
    copilot_allow_all: bool = True
    copilot_instructions_path: str = _default_copilot_instructions_path()
    tts_speak_partials: bool = True
    tts_partial_min_chars: int = 12
    tts_partial_force_flush_chars: int = 72

    @classmethod
    def from_env(cls) -> "Settings":
        _load_dotenv()
        copilot_instructions_path = os.getenv("PROXY_INSTRUCTIONS_PATH")
        if (
            copilot_instructions_path is None
            or copilot_instructions_path.strip() == ""
            or copilot_instructions_path.strip() == "~/.copilot/copilot-instructions.md"
        ):
            copilot_instructions_path = _default_copilot_instructions_path()
        return cls(
            deepgram_api_key=os.getenv("DEEPGRAM_API_KEY", ""),
            elevenlabs_api_key=os.getenv("ELEVENLABS_API_KEY", ""),
            elevenlabs_voice_id=os.getenv("ELEVENLABS_VOICE_ID", ""),
            elevenlabs_model_id=os.getenv("PROXY_ELEVENLABS_MODEL_ID", "eleven_multilingual_v2"),
            elevenlabs_output_format=os.getenv("PROXY_ELEVENLABS_OUTPUT_FORMAT", "pcm_22050"),
            elevenlabs_fallback_output_formats=_parse_csv(
                os.getenv("PROXY_ELEVENLABS_FALLBACK_OUTPUT_FORMATS", "wav_22050")
            ),
            elevenlabs_stability=float(os.getenv("PROXY_ELEVENLABS_STABILITY", "0.45")),
            elevenlabs_similarity_boost=float(
                os.getenv("PROXY_ELEVENLABS_SIMILARITY_BOOST", "0.85")
            ),
            elevenlabs_style=float(os.getenv("PROXY_ELEVENLABS_STYLE", "0.25")),
            elevenlabs_speed=float(os.getenv("PROXY_ELEVENLABS_SPEED", "0.95")),
            elevenlabs_use_speaker_boost=os.getenv("PROXY_ELEVENLABS_USE_SPEAKER_BOOST", "1")
            in ("1", "true", "True"),
            log_level=os.getenv("PROXY_LOG_LEVEL", "INFO"),
            log_debug_modules=os.getenv("PROXY_LOG_DEBUG_MODULES", ""),
            queue_maxsize=int(os.getenv("PROXY_QUEUE_MAXSIZE", "256")),
            audio_sample_rate=int(os.getenv("PROXY_AUDIO_SAMPLE_RATE", "16000")),
            audio_channels=int(os.getenv("PROXY_AUDIO_CHANNELS", "1")),
            audio_chunk_ms=int(os.getenv("PROXY_AUDIO_CHUNK_MS", "20")),
            audio_input_queue_maxsize=int(os.getenv("PROXY_AUDIO_INPUT_QUEUE_MAXSIZE", "128")),
            audio_input_device=os.getenv("PROXY_AUDIO_INPUT_DEVICE", ""),
            yes_asset_path=os.getenv("PROXY_YES_ASSET_PATH", "assets/yes.wav"),
            greetings_sounds_dir=os.getenv("PROXY_GREETINGS_SOUNDS_DIR", "assets/greetings"),
            wake_sounds_dir=os.getenv("PROXY_WAKE_SOUNDS_DIR", "assets/wake"),
            wake_phrase=os.getenv("PROXY_WAKE_PHRASE", "proxy"),
            wake_aliases=os.getenv("PROXY_WAKE_ALIASES", "proxy,roxy,rocky"),
            vosk_model_path=os.getenv(
                "PROXY_VOSK_MODEL_PATH", "assets/models/vosk-model-small-en-us-0.15"
            ),
            wake_debug_transcripts=os.getenv("PROXY_WAKE_DEBUG_TRANSCRIPTS", "0") in ("1", "true", "True"),
            wake_retrigger_cooldown_ms=int(os.getenv("PROXY_WAKE_RETRIGGER_COOLDOWN_MS", "1500")),
            wake_rearm_guard_ms=int(os.getenv("PROXY_WAKE_REARM_GUARD_MS", "1200")),
            wake_match_partial=os.getenv("PROXY_WAKE_MATCH_PARTIAL", "0")
            in ("1", "true", "True"),
            stopword_phrase=os.getenv("PROXY_STOPWORD_PHRASE", "stop"),
            stopword_aliases=os.getenv("PROXY_STOPWORD_ALIASES", "stop,shut up"),
            stopword_cooldown_ms=int(os.getenv("PROXY_STOPWORD_COOLDOWN_MS", "1500")),
            deepgram_model=os.getenv("PROXY_DEEPGRAM_MODEL", "nova-3"),
            deepgram_language=os.getenv("PROXY_DEEPGRAM_LANGUAGE", "en-US"),
            deepgram_endpointing_enabled=os.getenv("PROXY_DEEPGRAM_ENDPOINTING_ENABLED", "1")
            in ("1", "true", "True"),
            deepgram_endpointing_ms=int(os.getenv("PROXY_DEEPGRAM_ENDPOINTING_MS", "700")),
            deepgram_utterance_end_ms=int(os.getenv("PROXY_DEEPGRAM_UTTERANCE_END_MS", "3500")),
            deepgram_punctuate=os.getenv("PROXY_DEEPGRAM_PUNCTUATE", "1")
            in ("1", "true", "True"),
            deepgram_smart_format=os.getenv("PROXY_DEEPGRAM_SMART_FORMAT", "1")
            in ("1", "true", "True"),
            deepgram_keyterms=_parse_csv(os.getenv("PROXY_DEEPGRAM_KEYTERMS", "")),
            deepgram_interim_results=os.getenv("PROXY_DEEPGRAM_INTERIM_RESULTS", "1")
            in ("1", "true", "True"),
            deepgram_reconnect_max_attempts=int(
                os.getenv("PROXY_DEEPGRAM_RECONNECT_MAX_ATTEMPTS", "3")
            ),
            deepgram_reconnect_base_delay_ms=int(
                os.getenv("PROXY_DEEPGRAM_RECONNECT_BASE_DELAY_MS", "200")
            ),
            stt_gate_enabled=os.getenv("PROXY_STT_GATE_ENABLED", "1") in ("1", "true", "True"),
            stt_gate_hold_ms=int(os.getenv("PROXY_STT_GATE_HOLD_MS", "900")),
            stt_deecho_enabled=os.getenv("PROXY_STT_DEECHO_ENABLED", "1")
            in ("1", "true", "True"),
            stt_deecho_similarity_threshold=float(
                os.getenv("PROXY_STT_DEECHO_SIMILARITY_THRESHOLD", "0.78")
            ),
            listening_timeout_ms=int(os.getenv("PROXY_LISTENING_TIMEOUT_MS", "10000")),
            cancel_commands=os.getenv("PROXY_CANCEL_COMMANDS", "nevermind,never mind,quit"),
            copilot_command=os.getenv("PROXY_COPILOT_COMMAND", "copilot"),
            copilot_model=os.getenv("PROXY_COPILOT_MODEL", ""),
            copilot_allow_all=os.getenv("PROXY_COPILOT_ALLOW_ALL", "1")
            in ("1", "true", "True"),
            copilot_instructions_path=copilot_instructions_path,
            tts_speak_partials=os.getenv("PROXY_TTS_SPEAK_PARTIALS", "1")
            in ("1", "true", "True"),
            tts_partial_min_chars=max(1, int(os.getenv("PROXY_TTS_PARTIAL_MIN_CHARS", "12"))),
            tts_partial_force_flush_chars=max(
                0,
                int(os.getenv("PROXY_TTS_PARTIAL_FORCE_FLUSH_CHARS", "72")),
            ),
        )
