"""
ElevenLabs Text-To-Speech (TTS) Streaming Engine.
Provides high-fidelity multilingual neural speech generation with chunk-based progressive streaming.
"""

import os
import json
import logging
import httpx
from typing import AsyncGenerator, Tuple, List, Optional, Dict, Any

from doova_one_view.api.tts.engines.base import BaseTTSEngine
from doova_one_view.api.tts.schemas import VoiceInfo, ElevenLabsVoiceEnum

logger = logging.getLogger(__name__)

# Curated catalog of standard ElevenLabs voices supporting eleven_multilingual_v2
ELEVENLABS_VOICE_CATALOG: Dict[str, Dict[str, Any]] = {
    ElevenLabsVoiceEnum.RACHEL.value: {
        "enum": ElevenLabsVoiceEnum.RACHEL.name,
        "name": "Rachel",
        "lang": "en",
        "gender": "female",
        "language_name": "Multilingual",
        "description": "Universal Multilingual Voice",
    },
}

DEFAULT_ELEVENLABS_VOICES = {
    "en": ElevenLabsVoiceEnum.RACHEL.value,
    "ar": ElevenLabsVoiceEnum.RACHEL.value,
    "fr": ElevenLabsVoiceEnum.RACHEL.value,
    "es": ElevenLabsVoiceEnum.RACHEL.value,
}



class ElevenLabsEngine(BaseTTSEngine):
    """
    ElevenLabs Text-To-Speech engine utilizing eleven_multilingual_v2 with chunked streaming.
    """

    @property
    def engine_name(self) -> str:
        return "elevenlabs"

    def get_api_key(self) -> str:
        """Reads API key dynamically from environment or .env file."""
        from pathlib import Path
        from dotenv import load_dotenv
        env_path = Path(__file__).resolve().parent.parent.parent.parent / ".env"
        if env_path.exists():
            load_dotenv(env_path, override=True)
        return os.getenv("ELEVENLABS_API_KEY", "").strip()

    def get_default_voice_for_lang(self, lang: str) -> str:
        """Returns the default ElevenLabs voice identifier for a given language."""
        return DEFAULT_ELEVENLABS_VOICES.get(lang.lower(), DEFAULT_ELEVENLABS_VOICES["en"])

    def resolve_voice_id(self, voice: Optional[str] = None, default_lang: str = "en") -> str:
        """
        Resolves voice enum name or raw ID to a valid ElevenLabs voice ID.
        E.g. 'RACHEL' -> '21m00Tcm4TlvDq8ikWAM'
        """
        if not voice or voice.strip().lower() in ("auto", "none", ""):
            return self.get_default_voice_for_lang(default_lang)

        clean = voice.strip()
        # Check if it matches an enum key
        if clean.upper() in ElevenLabsVoiceEnum.__members__:
            return ElevenLabsVoiceEnum[clean.upper()].value

        # Check if already a valid voice id or custom id
        return clean

    def get_supported_voices(self) -> List[VoiceInfo]:
        """
        Returns Rachel as the universal ElevenLabs voice supporting eleven_multilingual_v2.
        """
        return [
            VoiceInfo(
                id=ElevenLabsVoiceEnum.RACHEL.value,
                name="Rachel",
                language="multi",
                language_name="Multilingual",
                gender="female",
                engine="elevenlabs",
                is_default=True,
                description="Universal Multilingual Voice (English, Arabic, French, Spanish)",
                voice_enum=ElevenLabsVoiceEnum.RACHEL.name,
            )
        ]

    async def synthesize_stream(
        self,
        text: str,
        voice: Optional[str] = None,
        speed: float = 1.0,
        lang: Optional[str] = None,
    ) -> AsyncGenerator[bytes, None]:
        """
        Synthesizes text and yields audio chunks asynchronously via ElevenLabs streaming API.
        """
        api_key = self.get_api_key()
        if not api_key:
            raise RuntimeError("ElevenLabs API key is missing. Set ELEVENLABS_API_KEY in .env.")

        voice_id = self.resolve_voice_id(voice)
        speed_factor = round(max(0.7, min(1.2, speed)), 2)

        url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream?optimize_streaming_latency=3"
        headers = {
            "xi-api-key": api_key,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        }

        # Split text into bite-sized sentence chunks (max 450 chars).
        # ElevenLabs autoregressive models (eleven_multilingual_v2) rush and accelerate to 2x-3x
        # when fed large monolithic blocks (>500 chars). Keeping chunks at ~450 chars
        # guarantees steady 1.0x conversational pacing throughout the entire speech.
        from doova_one_view.api.tts.cleaner import split_text_into_sentences
        text_pieces = split_text_into_sentences(text, max_chunk_chars=450)

        timeout = httpx.Timeout(60.0, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            for piece in text_pieces:
                if not piece.strip():
                    continue

                clean_lang = (lang or "en").lower().strip()
                is_ar = clean_lang == "ar"
                stability = 0.55 if is_ar else 0.70
                similarity = 0.65 if is_ar else 0.80

                payload = {
                    "text": piece.strip(),
                    "model_id": "eleven_turbo_v2_5",
                    "voice_settings": {
                        "stability": stability,
                        "similarity_boost": similarity,
                        "speed": speed_factor,
                    },
                }
                if clean_lang in ("en", "ar", "fr", "es"):
                    payload["language_code"] = clean_lang


                async with client.stream("POST", url, headers=headers, json=payload) as response:
                    if response.status_code != 200:
                        err_bytes = await response.aread()
                        err_str = err_bytes.decode("utf-8", errors="replace")
                        try:
                            err_json = json.loads(err_str)
                            if isinstance(err_json.get("detail"), dict):
                                detail_msg = err_json["detail"].get("message", err_str)
                            else:
                                detail_msg = err_json.get("detail", err_str)
                        except Exception:
                            detail_msg = err_str
                        raise RuntimeError(f"ElevenLabs API error ({response.status_code}): {detail_msg}")

                    async for chunk in response.aiter_bytes():
                        if chunk:
                            yield chunk

    async def synthesize(
        self,
        text: str,
        voice: Optional[str] = None,
        speed: float = 1.0,
        lang: Optional[str] = None,
    ) -> Tuple[bytes, str, str]:
        """
        Synthesizes text into full MP3 audio bytes.
        Returns: (audio_bytes, media_type, file_extension) e.g. (b'...', 'audio/mpeg', 'mp3')
        """
        chunks = []
        async for chunk in self.synthesize_stream(text=text, voice=voice, speed=speed, lang=lang):
            chunks.append(chunk)
        audio_bytes = b"".join(chunks)
        return audio_bytes, "audio/mpeg", "mp3"
