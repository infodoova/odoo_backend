"""
Central Text-To-Speech (TTS) orchestration service.
Combines cleaner, language detection, engine dispatching (Edge-TTS vs Piper), and audio caching.
"""

import asyncio
import logging
from typing import Optional, Tuple, List, AsyncGenerator
from pathlib import Path

from doova_one_view.api.tts.schemas import VoiceInfo, VoiceListResponse
from doova_one_view.api.tts.cleaner import clean_text_for_speech, split_text_into_sentences
from doova_one_view.api.tts.detector import detect_language
from doova_one_view.api.tts.cache import TTSCacheManager
from doova_one_view.api.tts.engines.piper_engine import PiperEngine, PIPER_VOICE_CATALOG, combine_wav_buffers
from doova_one_view.api.tts.engines.edge_engine import EdgeEngine, EDGE_VOICE_CATALOG, DEFAULT_EDGE_VOICES

logger = logging.getLogger(__name__)


class TTSService:
    """
    Unified TTS Service managing language routing, engine selection, and caching.
    """

    def __init__(self):
        self.piper_engine = PiperEngine()
        self.edge_engine = EdgeEngine()
        self.cache = TTSCacheManager()

    def get_available_voices(self) -> VoiceListResponse:
        """Returns catalog of all supported voices across all engines."""
        edge_voices = self.edge_engine.get_supported_voices()
        piper_voices = self.piper_engine.get_supported_voices()
        all_voices = edge_voices + piper_voices

        languages = sorted(list(set(v.language for v in all_voices)))
        engines = ["edge-tts", "piper"]

        return VoiceListResponse(
            voices=all_voices,
            engines=engines,
            languages=languages,
        )

    def resolve_language_and_voice(
        self,
        text: str,
        lang: Optional[str] = "auto",
        voice: Optional[str] = None
    ) -> Tuple[str, str, str]:
        """
        Determines the effective language, engine, and voice model.
        Returns: (resolved_lang, engine_name, resolved_voice)
        """
        # If specific voice passed, check which engine owns it
        if voice and voice != "Auto":
            if voice in EDGE_VOICE_CATALOG:
                voice_meta = EDGE_VOICE_CATALOG[voice]
                return voice_meta["lang"], "edge-tts", voice
            if voice in PIPER_VOICE_CATALOG:
                voice_meta = PIPER_VOICE_CATALOG[voice]
                return voice_meta["lang"], "piper", voice

        # Resolve language
        target_lang = (lang or "auto").lower().strip()
        if target_lang == "auto" or target_lang not in {"en", "fr", "es", "ar"}:
            target_lang = detect_language(text, fallback="en")

        # Edge-TTS is primary for all supported languages (high speed, human quality neural voices)
        default_voice = self.edge_engine.get_default_voice_for_lang(target_lang)
        return target_lang, "edge-tts", voice if (voice and voice != "Auto") else default_voice

    async def synthesize(
        self,
        text: str,
        lang: Optional[str] = "auto",
        voice: Optional[str] = None,
        speed: float = 1.0,
    ) -> Tuple[bytes, str, dict]:
        """
        Full synthesis with caching and automatic fallback.
        Returns: (audio_bytes, media_type, metadata_dict)
        """
        clean_text = clean_text_for_speech(text)
        if not clean_text:
            raise ValueError("Input text is empty after preprocessing.")

        resolved_lang, engine_name, resolved_voice = self.resolve_language_and_voice(
            clean_text, lang=lang, voice=voice
        )

        ext = "mp3" if engine_name == "edge-tts" else "wav"
        media_type = "audio/mpeg" if engine_name == "edge-tts" else "audio/wav"

        cache_key = self.cache.generate_key(engine_name, resolved_voice, speed, clean_text)

        # 1. Check disk cache
        cached_bytes = self.cache.get_cached_bytes(cache_key, ext)
        if cached_bytes:
            metadata = {
                "engine": engine_name,
                "language": resolved_lang,
                "voice": resolved_voice,
                "cached": True,
                "clean_text": clean_text,
            }
            return cached_bytes, media_type, metadata

        # 2. Synthesize with Edge-TTS or Piper
        try:
            if engine_name == "edge-tts":
                audio_bytes, media_type, ext = await self.edge_engine.synthesize(
                    text=clean_text, voice=resolved_voice, speed=speed
                )
            else:
                # Piper sentence-by-sentence with PCM frame stitching
                text_chunks = split_text_into_sentences(clean_text, max_chunk_chars=350)
                collected_chunks = []
                for chunk in text_chunks:
                    chunk_bytes, _, _ = await self.piper_engine.synthesize(
                        text=chunk, voice=resolved_voice, speed=speed
                    )
                    collected_chunks.append(chunk_bytes)
                audio_bytes = combine_wav_buffers(collected_chunks)

        except Exception as e:
            if engine_name == "edge-tts":
                logger.warning(f"Edge-TTS failed ({e}), falling back to Piper offline engine...")
                engine_name = "piper"
                resolved_voice = self.piper_engine.get_default_voice_for_lang(resolved_lang)
                ext = "wav"
                media_type = "audio/wav"
                text_chunks = split_text_into_sentences(clean_text, max_chunk_chars=350)
                collected_chunks = []
                for chunk in text_chunks:
                    chunk_bytes, _, _ = await self.piper_engine.synthesize(
                        text=chunk, voice=resolved_voice, speed=speed
                    )
                    collected_chunks.append(chunk_bytes)
                audio_bytes = combine_wav_buffers(collected_chunks)
            else:
                raise e

        # 3. Save to disk cache
        self.cache.save_cached_audio(cache_key, ext, audio_bytes)

        metadata = {
            "engine": engine_name,
            "language": resolved_lang,
            "voice": resolved_voice,
            "cached": False,
            "clean_text": clean_text,
        }
        return audio_bytes, media_type, metadata

    async def synthesize_stream(
        self,
        text: str,
        lang: Optional[str] = "auto",
        voice: Optional[str] = None,
        speed: float = 1.0,
    ) -> Tuple[AsyncGenerator[bytes, None], str, dict]:
        """
        Streaming synthesis generator with sentence-level progressive chunking and caching.
        Returns: (async_chunk_generator, media_type, metadata_dict)
        """
        clean_text = clean_text_for_speech(text)
        if not clean_text:
            raise ValueError("Input text is empty after preprocessing.")

        resolved_lang, engine_name, resolved_voice = self.resolve_language_and_voice(
            clean_text, lang=lang, voice=voice
        )

        ext = "mp3" if engine_name == "edge-tts" else "wav"
        media_type = "audio/mpeg" if engine_name == "edge-tts" else "audio/wav"

        cache_key = self.cache.generate_key(engine_name, resolved_voice, speed, clean_text)
        cached_file = self.cache.get_cached_file(cache_key, ext)

        metadata = {
            "engine": engine_name,
            "language": resolved_lang,
            "voice": resolved_voice,
            "cached": cached_file is not None,
            "clean_text": clean_text,
        }

        # If full text is already cached, stream directly from file in 8KB chunks
        if cached_file:
            async def file_stream_generator():
                chunk_size = 8192
                with open(cached_file, "rb") as f:
                    while True:
                        chunk = f.read(chunk_size)
                        if not chunk:
                            break
                        yield chunk
                        await asyncio.sleep(0)

            return file_stream_generator(), media_type, metadata

        # For live streaming:
        # Edge-TTS produces MP3 frames which stream in real time seamlessly
        if engine_name == "edge-tts":
            accumulated: List[bytes] = []

            async def edge_stream_generator():
                try:
                    stream = self.edge_engine.synthesize_stream(
                        text=clean_text, voice=resolved_voice, speed=speed
                    )
                    async for chunk in stream:
                        accumulated.append(chunk)
                        yield chunk
                except Exception as stream_err:
                    logger.warning(f"Edge-TTS stream error ({stream_err}), falling back to Piper...")
                    # Fallback to Piper
                    fallback_audio, _, _ = await self.piper_engine.synthesize(
                        text=clean_text, voice=self.piper_engine.get_default_voice_for_lang(resolved_lang), speed=speed
                    )
                    accumulated.clear()
                    accumulated.append(fallback_audio)
                    for i in range(0, len(fallback_audio), 8192):
                        yield fallback_audio[i : i + 8192]
                finally:
                    if accumulated:
                        all_mp3 = b"".join(accumulated)
                        self.cache.save_cached_audio(cache_key, ext, all_mp3)

            return edge_stream_generator(), media_type, metadata

        else:
            # Piper WAV generation: synthesize chunks, combine PCM frames, and stream combined WAV
            async def piper_stream_generator():
                text_chunks = split_text_into_sentences(clean_text, max_chunk_chars=350)
                collected = []
                for ch in text_chunks:
                    b, _, _ = await self.piper_engine.synthesize(
                        text=ch, voice=resolved_voice, speed=speed
                    )
                    collected.append(b)
                full_wav = combine_wav_buffers(collected)
                self.cache.save_cached_audio(cache_key, ext, full_wav)
                for i in range(0, len(full_wav), 8192):
                    yield full_wav[i : i + 8192]
                    await asyncio.sleep(0)

            return piper_stream_generator(), media_type, metadata


# Global singleton instance
tts_service = TTSService()
