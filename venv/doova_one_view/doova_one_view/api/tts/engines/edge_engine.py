"""
Edge-TTS Engine implementation for Arabic, English, French, and Spanish.
High-fidelity Microsoft Azure / Edge Neural TTS voices with zero API key required.
Fast, realistic, and streaming-friendly (MP3).
"""

import io
import asyncio
import logging
from typing import Dict, List, Optional, Tuple, AsyncGenerator
import edge_tts

from doova_one_view.api.tts.engines.base import BaseTTSEngine
from doova_one_view.api.tts.schemas import VoiceInfo

logger = logging.getLogger(__name__)

# Curated catalog of top-quality Neural voices
EDGE_VOICE_CATALOG: Dict[str, dict] = {
    # --- English ---
    "en-US-AriaNeural": {
        "name": "Aria (US English)",
        "lang": "en",
        "lang_name": "English (US)",
        "gender": "female",
        "is_default": True,
    },
    "en-US-GuyNeural": {
        "name": "Guy (US English)",
        "lang": "en",
        "lang_name": "English (US)",
        "gender": "male",
        "is_default": False,
    },
    "en-US-JennyNeural": {
        "name": "Jenny (US English)",
        "lang": "en",
        "lang_name": "English (US)",
        "gender": "female",
        "is_default": False,
    },
    "en-GB-SoniaNeural": {
        "name": "Sonia (UK English)",
        "lang": "en",
        "lang_name": "English (UK)",
        "gender": "female",
        "is_default": False,
    },

    # --- Arabic ---
    "ar-SA-HamedNeural": {
        "name": "Hamed (Saudi Arabic)",
        "lang": "ar",
        "lang_name": "Arabic (Saudi Arabia)",
        "gender": "male",
        "is_default": True,
    },
    "ar-SA-ZariyahNeural": {
        "name": "Zariyah (Saudi Arabic)",
        "lang": "ar",
        "lang_name": "Arabic (Saudi Arabia)",
        "gender": "female",
        "is_default": False,
    },
    "ar-EG-SalmaNeural": {
        "name": "Salma (Egyptian Arabic)",
        "lang": "ar",
        "lang_name": "Arabic (Egypt)",
        "gender": "female",
        "is_default": False,
    },
    "ar-EG-ShakirNeural": {
        "name": "Shakir (Egyptian Arabic)",
        "lang": "ar",
        "lang_name": "Arabic (Egypt)",
        "gender": "male",
        "is_default": False,
    },
    "ar-AE-FatimaNeural": {
        "name": "Fatima (Emirati Arabic)",
        "lang": "ar",
        "lang_name": "Arabic (UAE)",
        "gender": "female",
        "is_default": False,
    },
    "ar-AE-HamdanNeural": {
        "name": "Hamdan (Emirati Arabic)",
        "lang": "ar",
        "lang_name": "Arabic (UAE)",
        "gender": "male",
        "is_default": False,
    },

    # --- French ---
    "fr-FR-DeniseNeural": {
        "name": "Denise (French)",
        "lang": "fr",
        "lang_name": "French (France)",
        "gender": "female",
        "is_default": True,
    },
    "fr-FR-HenriNeural": {
        "name": "Henri (French)",
        "lang": "fr",
        "lang_name": "French (France)",
        "gender": "male",
        "is_default": False,
    },

    # --- Spanish ---
    "es-ES-ElviraNeural": {
        "name": "Elvira (Spanish)",
        "lang": "es",
        "lang_name": "Spanish (Spain)",
        "gender": "female",
        "is_default": True,
    },
    "es-ES-AlvaroNeural": {
        "name": "Alvaro (Spanish)",
        "lang": "es",
        "lang_name": "Spanish (Spain)",
        "gender": "male",
        "is_default": False,
    },
}

DEFAULT_EDGE_VOICES = {
    "ar": "ar-SA-HamedNeural",
    "en": "en-US-AriaNeural",
    "fr": "fr-FR-DeniseNeural",
    "es": "es-ES-ElviraNeural",
}


def _format_rate(speed: float) -> str:
    """Converts a speed multiplier (e.g. 1.2 or 0.8) into edge-tts rate string (e.g. '+20%' or '-20%')."""
    percent = int(round((speed - 1.0) * 100))
    return f"{percent:+d}%"


class EdgeEngine(BaseTTSEngine):
    """
    High-fidelity neural TTS engine using Edge-TTS.
    """

    @property
    def engine_name(self) -> str:
        return "edge-tts"

    def get_supported_voices(self) -> List[VoiceInfo]:
        """Returns VoiceInfo list for all supported Edge-TTS voices."""
        result = []
        for voice_id, meta in EDGE_VOICE_CATALOG.items():
            result.append(
                VoiceInfo(
                    id=voice_id,
                    name=meta["name"],
                    language=meta["lang"],
                    language_name=meta["lang_name"],
                    gender=meta["gender"],
                    engine="edge-tts",
                    is_default=meta.get("is_default", False),
                )
            )
        return result

    def get_default_voice_for_lang(self, lang: str) -> str:
        return DEFAULT_EDGE_VOICES.get(lang, "en-US-AriaNeural")

    def get_default_voice(self) -> str:
        return DEFAULT_EDGE_VOICES["ar"]

    async def synthesize(
        self,
        text: str,
        voice: Optional[str] = None,
        speed: float = 1.0
    ) -> Tuple[bytes, str, str]:
        """
        Synthesizes text into complete MP3 bytes.
        Returns: (audio_bytes, "audio/mpeg", "mp3")
        """
        voice_id = voice or "en-US-AriaNeural"
        rate = _format_rate(speed)

        async def _fetch():
            communicate = edge_tts.Communicate(text=text, voice=voice_id, rate=rate)
            chunks = []
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    chunks.append(chunk["data"])
            return b"".join(chunks)

        try:
            audio_bytes = await asyncio.wait_for(_fetch(), timeout=25.0)
        except asyncio.TimeoutError:
            raise TimeoutError(f"Edge-TTS synthesis request timed out for voice '{voice_id}' (25s).")

        return audio_bytes, "audio/mpeg", "mp3"

    async def synthesize_stream(
        self,
        text: str,
        voice: Optional[str] = None,
        speed: float = 1.0
    ) -> AsyncGenerator[bytes, None]:
        """
        Synthesizes text and yields MP3 audio chunks in real-time.
        """
        voice_id = voice or "en-US-AriaNeural"
        rate = _format_rate(speed)

        communicate = edge_tts.Communicate(text=text, voice=voice_id, rate=rate)
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                yield chunk["data"]
