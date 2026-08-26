"""
Piper TTS Engine implementation for Arabic, English, French, and Spanish.
Fast, offline neural VITS synthesis running locally with ONNX Runtime.
"""

import io
import wave
import urllib.request
import asyncio
import logging
import threading
from pathlib import Path
from typing import Dict, List, Optional, Tuple, AsyncGenerator
from django.conf import settings

from doova_one_view.api.tts.engines.base import BaseTTSEngine
from doova_one_view.api.tts.schemas import VoiceInfo

logger = logging.getLogger(__name__)

# HuggingFace repository base URL for official Piper voices
PIPER_HF_BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/main"

# Pre-configured voice catalog for Arabic, English, French, and Spanish
PIPER_VOICE_CATALOG: Dict[str, dict] = {
    # --- Arabic (Offline) ---
    "ar_JO-kareem-medium": {
        "name": "Kareem (Arabic - Offline)",
        "lang": "ar",
        "lang_name": "Arabic (Jordan)",
        "gender": "male",
        "is_default": False,
        "hf_path": "ar/ar_JO/kareem/medium/ar_JO-kareem-medium",
    },
    "ar_JO-kareem-low": {
        "name": "Kareem Fast (Arabic - Offline)",
        "lang": "ar",
        "lang_name": "Arabic (Jordan)",
        "gender": "male",
        "is_default": False,
        "hf_path": "ar/ar_JO/kareem/low/ar_JO-kareem-low",
    },

    # --- English (Offline) ---
    "en_US-lessac-medium": {
        "name": "Lessac (US English - Offline)",
        "lang": "en",
        "lang_name": "English",
        "gender": "female",
        "is_default": False,
        "hf_path": "en/en_US/lessac/medium/en_US-lessac-medium",
    },

    # --- French (Offline) ---
    "fr_FR-siwis-medium": {
        "name": "Siwis (French - Offline)",
        "lang": "fr",
        "lang_name": "French",
        "gender": "female",
        "is_default": False,
        "hf_path": "fr/fr_FR/siwis/medium/fr_FR-siwis-medium",
    },

    # --- Spanish (Offline) ---
    "es_ES-davefx-medium": {
        "name": "Dave (Spanish - Offline)",
        "lang": "es",
        "lang_name": "Spanish",
        "gender": "male",
        "is_default": False,
        "hf_path": "es/es_ES/davefx/medium/es_ES-davefx-medium",
    },
}

DEFAULT_LANG_VOICES = {
    "ar": "ar_JO-kareem-medium",
    "en": "en_US-lessac-medium",
    "fr": "fr_FR-siwis-medium",
    "es": "es_ES-davefx-medium",
}


def combine_wav_buffers(wav_list: List[bytes]) -> bytes:
    """
    Combines multiple WAV byte buffers into a single valid WAV file with correct header.
    """
    if not wav_list:
        return b""
    if len(wav_list) == 1:
        return wav_list[0]

    buf = io.BytesIO()
    with wave.open(buf, "wb") as out_wav:
        for idx, wav_raw in enumerate(wav_list):
            if not wav_raw or len(wav_raw) < 44:
                continue
            with wave.open(io.BytesIO(wav_raw), "rb") as in_wav:
                if idx == 0:
                    out_wav.setnchannels(in_wav.getnchannels())
                    out_wav.setsampwidth(in_wav.getsampwidth())
                    out_wav.setframerate(in_wav.getframerate())
                frames = in_wav.readframes(in_wav.getnframes())
                out_wav.writeframes(frames)

    return buf.getvalue()


class PiperEngine(BaseTTSEngine):
    """
    Offline neural TTS engine using Piper ONNX models.
    """

    def __init__(self, models_dir: Optional[Path] = None):
        if models_dir is None:
            base_dir = getattr(settings, "BASE_DIR", Path(__file__).resolve().parents[5])
            self.models_dir = Path(base_dir) / "storage_uploads" / "tts_models"
        else:
            self.models_dir = Path(models_dir)

        self.models_dir.mkdir(parents=True, exist_ok=True)
        self._loaded_voices: Dict[str, object] = {}
        self._lock = threading.Lock()

    @property
    def engine_name(self) -> str:
        return "piper"

    def get_supported_voices(self) -> List[VoiceInfo]:
        """Returns VoiceInfo list for all supported Piper voices."""
        result = []
        for voice_id, meta in PIPER_VOICE_CATALOG.items():
            result.append(
                VoiceInfo(
                    id=voice_id,
                    name=meta["name"],
                    language=meta["lang"],
                    language_name=meta["lang_name"],
                    gender=meta["gender"],
                    engine="piper",
                    is_default=meta.get("is_default", False),
                )
            )
        return result

    def get_default_voice_for_lang(self, lang: str) -> str:
        return DEFAULT_LANG_VOICES.get(lang, "en_US-lessac-medium")

    def _ensure_model_downloaded(self, voice_id: str) -> Tuple[Path, Path]:
        """
        Ensures the .onnx and .onnx.json files exist locally, downloading them if needed.
        """
        if voice_id not in PIPER_VOICE_CATALOG:
            raise ValueError(f"Unknown Piper voice: '{voice_id}'. Supported: {list(PIPER_VOICE_CATALOG.keys())}")

        meta = PIPER_VOICE_CATALOG[voice_id]
        onnx_file = self.models_dir / f"{voice_id}.onnx"
        json_file = self.models_dir / f"{voice_id}.onnx.json"

        if not onnx_file.exists() or not json_file.exists():
            hf_path = meta["hf_path"]
            onnx_url = f"{PIPER_HF_BASE}/{hf_path}.onnx"
            json_url = f"{PIPER_HF_BASE}/{hf_path}.onnx.json"

            logger.info(f"Downloading Piper voice '{voice_id}' from {onnx_url}...")
            req_headers = {"User-Agent": "DoovaOneView-TTS/1.0"}

            # Download json config first
            if not json_file.exists():
                req = urllib.request.Request(json_url, headers=req_headers)
                with urllib.request.urlopen(req, timeout=30) as resp, open(json_file, "wb") as out:
                    out.write(resp.read())

            # Download ONNX weights
            if not onnx_file.exists():
                req = urllib.request.Request(onnx_url, headers=req_headers)
                with urllib.request.urlopen(req, timeout=120) as resp, open(onnx_file, "wb") as out:
                    out.write(resp.read())

            logger.info(f"Successfully downloaded Piper voice '{voice_id}' to {self.models_dir}")

        return onnx_file, json_file

    def _get_or_load_voice(self, voice_id: str):
        """Thread-safe lazy-loading of PiperVoice model."""
        with self._lock:
            if voice_id in self._loaded_voices:
                return self._loaded_voices[voice_id]

            onnx_file, json_file = self._ensure_model_downloaded(voice_id)

            from piper.voice import PiperVoice
            voice = PiperVoice.load(model_path=onnx_file, config_path=json_file)
            self._loaded_voices[voice_id] = voice
            return voice

    def _synthesize_sync(self, text: str, voice_id: str, speed: float = 1.0) -> bytes:
        """Synchronous synthesis executed in thread pool."""
        voice = self._get_or_load_voice(voice_id)

        # Piper speed is configured via length_scale (lower = faster)
        length_scale = max(0.5, min(2.0, 1.0 / max(speed, 0.1)))

        from piper.config import SynthesisConfig
        syn_config = SynthesisConfig(length_scale=length_scale)

        buf = io.BytesIO()
        with wave.open(buf, "wb") as wav_file:
            voice.synthesize_wav(
                text=text,
                wav_file=wav_file,
                syn_config=syn_config,
                set_wav_format=True,
            )

        return buf.getvalue()

    async def synthesize(
        self,
        text: str,
        voice: Optional[str] = None,
        speed: float = 1.0
    ) -> Tuple[bytes, str, str]:
        """
        Synthesizes text into complete WAV bytes.
        Returns: (audio_bytes, "audio/wav", "wav")
        """
        voice_id = voice or "en_US-lessac-medium"
        audio_bytes = await asyncio.to_thread(self._synthesize_sync, text, voice_id, speed)
        return audio_bytes, "audio/wav", "wav"

    async def synthesize_stream(
        self,
        text: str,
        voice: Optional[str] = None,
        speed: float = 1.0
    ) -> AsyncGenerator[bytes, None]:
        """
        Yields WAV audio in streaming chunks.
        """
        audio_bytes, _, _ = await self.synthesize(text, voice, speed)
        # Stream in 8KB chunks for instant progressive playback
        chunk_size = 8192
        for i in range(0, len(audio_bytes), chunk_size):
            yield audio_bytes[i : i + chunk_size]
            await asyncio.sleep(0)
