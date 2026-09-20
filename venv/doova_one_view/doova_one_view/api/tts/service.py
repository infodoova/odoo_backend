"""
Central Text-To-Speech (TTS) orchestration service.
Combines cleaner, language detection, engine dispatching (ElevenLabs primary, with Edge-TTS and Piper fallback),
and audio caching.
"""

import os
import asyncio
import logging
from typing import Optional, Tuple, List, AsyncGenerator
from pathlib import Path

from doova_one_view.api.tts.schemas import VoiceInfo, VoiceListResponse, ElevenLabsVoiceEnum
from doova_one_view.api.tts.cleaner import clean_text_for_speech, split_text_into_sentences
from doova_one_view.api.tts.detector import detect_language
from doova_one_view.api.tts.cache import TTSCacheManager
from doova_one_view.api.tts.engines.piper_engine import PiperEngine, PIPER_VOICE_CATALOG, combine_wav_buffers
from doova_one_view.api.tts.engines.edge_engine import EdgeEngine, EDGE_VOICE_CATALOG, DEFAULT_EDGE_VOICES
from doova_one_view.api.tts.engines.elevenlabs_engine import (
    ElevenLabsEngine,
    ELEVENLABS_VOICE_CATALOG,
    DEFAULT_ELEVENLABS_VOICES,
)

logger = logging.getLogger(__name__)


class TTSService:
    """
    Unified TTS Service managing language routing, engine selection, and caching.
    Prioritizes ElevenLabs streaming in chunks. Supports conditional fallback to Edge-TTS / Piper
    controlled by TTS_FALLBACK environment variable.
    """

    def __init__(self):
        self.elevenlabs_engine = ElevenLabsEngine()
        self.piper_engine = PiperEngine()
        self.edge_engine = EdgeEngine()
        self.cache = TTSCacheManager()

    def is_fallback_enabled(self) -> bool:
        """
        Checks whether TTS fallback to Piper/Edge-TTS is permitted.
        Reads TTS_FALLBACK dynamically from environment or .env file (defaults to False).
        """
        env_path = Path(__file__).resolve().parent.parent.parent.parent / ".env"
        if env_path.exists():
            from dotenv import load_dotenv
            load_dotenv(env_path, override=True)
        val = os.getenv("TTS_FALLBACK", "false").strip().lower()
        return val in ("true", "1", "yes", "on")

    def get_available_voices(self) -> VoiceListResponse:
        """Returns catalog of all supported voices across all engines including enum mappings."""
        eleven_voices = self.elevenlabs_engine.get_supported_voices()
        edge_voices = self.edge_engine.get_supported_voices()
        piper_voices = self.piper_engine.get_supported_voices()
        all_voices = eleven_voices + edge_voices + piper_voices

        languages = sorted(list(set(v.language for v in all_voices)))
        engines = ["elevenlabs", "edge-tts", "piper"]

        return VoiceListResponse(
            voices=all_voices,
            engines=engines,
            languages=languages,
            voice_enums={e.name: e.value for e in ElevenLabsVoiceEnum},
        )

    def resolve_language_and_voice(
        self,
        text: str,
        lang: Optional[str] = "auto",
        voice: Optional[str] = None
    ) -> Tuple[str, str, str]:
        """
        Determines the effective language, engine, and voice model.
        Supports ElevenLabs enum names (e.g. 'RACHEL'), voice IDs, and engine catalogs.
        Returns: (resolved_lang, engine_name, resolved_voice)
        """
        # Resolve language
        target_lang = (lang or "auto").lower().strip()
        if target_lang == "auto" or target_lang not in {"en", "fr", "es", "ar"}:
            target_lang = detect_language(text, fallback="en")
        else:
            # Reconcile requested language with the actual script of the text:
            # If user settings are 'ar', but text is 100% English Latin characters with NO Arabic:
            from doova_one_view.api.tts.detector import ARABIC_PATTERN
            has_arabic = bool(ARABIC_PATTERN.search(text))
            if target_lang == "ar" and not has_arabic and any(c.isalpha() and c.isascii() for c in text):
                target_lang = detect_language(text, fallback="en")
            elif target_lang != "ar" and has_arabic:
                target_lang = "ar"

        # If specific voice passed, check which engine owns it
        if voice and voice != "Auto":
            clean_voice = voice.strip()
            # Support enum names (e.g. 'RACHEL', 'ADAM', etc.)
            if clean_voice.upper() in ElevenLabsVoiceEnum.__members__:
                resolved_id = ElevenLabsVoiceEnum[clean_voice.upper()].value
                return target_lang, "elevenlabs", resolved_id

            if clean_voice in EDGE_VOICE_CATALOG:
                voice_meta = EDGE_VOICE_CATALOG[clean_voice]
                return voice_meta["lang"], "edge-tts", clean_voice
            if clean_voice in PIPER_VOICE_CATALOG:
                voice_meta = PIPER_VOICE_CATALOG[clean_voice]
                return voice_meta["lang"], "piper", clean_voice
            if clean_voice in ELEVENLABS_VOICE_CATALOG:
                # Do NOT overwrite target_lang with voice_meta["lang"]!
                # ElevenLabs multilingual models speak in target_lang.
                return target_lang, "elevenlabs", clean_voice
            # Arbitrary voice ID treated as ElevenLabs custom voice ID
            return target_lang, "elevenlabs", clean_voice

        # ElevenLabs is the primary engine across all supported languages
        default_voice = self.elevenlabs_engine.get_default_voice_for_lang(target_lang)
        return target_lang, "elevenlabs", default_voice

    async def synthesize(
        self,
        text: str,
        lang: Optional[str] = "auto",
        voice: Optional[str] = None,
        speed: float = 1.0,
    ) -> Tuple[bytes, str, dict]:
        """
        Full synthesis with caching and conditional fallback.
        Returns: (audio_bytes, media_type, metadata_dict)
        """
        resolved_lang, engine_name, resolved_voice = self.resolve_language_and_voice(
            text, lang=lang, voice=voice
        )
        clean_text = clean_text_for_speech(text, lang=resolved_lang)
        if not clean_text:
            raise ValueError("Input text is empty after preprocessing.")

        ext = "mp3" if engine_name in ("elevenlabs", "edge-tts") else "wav"
        media_type = "audio/mpeg" if engine_name in ("elevenlabs", "edge-tts") else "audio/wav"

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

        is_fallback = False

        # 2. Synthesize with primary engine (ElevenLabs) or explicitly requested engine
        if engine_name == "elevenlabs":
            try:
                audio_bytes, media_type, ext = await self.elevenlabs_engine.synthesize(
                    text=clean_text, voice=resolved_voice, speed=speed, lang=resolved_lang
                )
            except Exception as e:
                if not self.is_fallback_enabled():
                    logger.error(
                        f"ElevenLabs TTS failed ({e}). Fallback is disabled (TTS_FALLBACK=false). "
                        "Returning error directly without invoking Edge-TTS or Piper."
                    )
                    raise e

                is_fallback = True
                logger.warning(
                    f"ElevenLabs TTS failed ({e}). Fallback is enabled (TTS_FALLBACK=true). "
                    "Falling back to Edge-TTS / Piper..."
                )
                try:
                    engine_name = "edge-tts"
                    resolved_voice = self.edge_engine.get_default_voice_for_lang(resolved_lang)
                    ext = "mp3"
                    media_type = "audio/mpeg"
                    audio_bytes, media_type, ext = await self.edge_engine.synthesize(
                        text=clean_text, voice=resolved_voice, speed=speed
                    )
                except Exception as edge_err:
                    logger.warning(f"Edge-TTS fallback also failed ({edge_err}), falling back to Piper...")
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

        elif engine_name == "edge-tts":
            try:
                audio_bytes, media_type, ext = await self.edge_engine.synthesize(
                    text=clean_text, voice=resolved_voice, speed=speed
                )
            except Exception as e:
                if not self.is_fallback_enabled():
                    raise e
                is_fallback = True
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
            # Piper engine directly
            text_chunks = split_text_into_sentences(clean_text, max_chunk_chars=350)
            collected_chunks = []
            for chunk in text_chunks:
                chunk_bytes, _, _ = await self.piper_engine.synthesize(
                    text=chunk, voice=resolved_voice, speed=speed
                )
                collected_chunks.append(chunk_bytes)
            audio_bytes = combine_wav_buffers(collected_chunks)

        # 3. Save to disk cache ONLY if it succeeded with the intended engine (never save fallback to cache)
        if not is_fallback:
            self.cache.save_cached_audio(cache_key, ext, audio_bytes)

        metadata = {
            "engine": engine_name,
            "language": resolved_lang,
            "voice": resolved_voice,
            "cached": False,
            "clean_text": clean_text,
            "fallback": is_fallback,
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
        Streaming synthesis generator with chunk-based progressive streaming and caching.
        Returns: (async_chunk_generator, media_type, metadata_dict)
        """
        resolved_lang, engine_name, resolved_voice = self.resolve_language_and_voice(
            text, lang=lang, voice=voice
        )
        clean_text = clean_text_for_speech(text, lang=resolved_lang)
        if not clean_text:
            raise ValueError("Input text is empty after preprocessing.")

        ext = "mp3" if engine_name in ("elevenlabs", "edge-tts") else "wav"
        media_type = "audio/mpeg" if engine_name in ("elevenlabs", "edge-tts") else "audio/wav"

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

        # 1. Primary engine: ElevenLabs chunked progressive stream
        if engine_name == "elevenlabs":
            accumulated: List[bytes] = []

            async def raw_eleven_generator():
                stream = self.elevenlabs_engine.synthesize_stream(
                    text=clean_text, voice=resolved_voice, speed=speed, lang=resolved_lang
                )
                async for chunk in stream:
                    accumulated.append(chunk)
                    yield chunk

            # Attempt to initialize stream and fetch first chunk to detect errors upfront
            try:
                eleven_gen = raw_eleven_generator()
                first_chunk = await eleven_gen.__anext__()

                async def wrapped_eleven_generator():
                    yield first_chunk
                    success = True
                    try:
                        async for ch in eleven_gen:
                            yield ch
                    except Exception as stream_err:
                        success = False
                        logger.error(f"ElevenLabs stream broke mid-stream: {stream_err}")
                        raise stream_err
                    finally:
                        if success and accumulated:
                            all_mp3 = b"".join(accumulated)
                            self.cache.save_cached_audio(cache_key, ext, all_mp3)

                return wrapped_eleven_generator(), media_type, metadata

            except StopAsyncIteration:
                # Empty stream
                async def empty_generator():
                    if False:
                        yield b""
                return empty_generator(), media_type, metadata

            except Exception as e:
                if not self.is_fallback_enabled():
                    logger.error(
                        f"ElevenLabs TTS failed ({e}). Fallback is disabled (TTS_FALLBACK=false). "
                        "Returning error directly without calling Edge-TTS or Piper."
                    )
                    raise e

                logger.warning(
                    f"ElevenLabs TTS failed ({e}). Fallback is enabled (TTS_FALLBACK=true). "
                    "Falling back to Edge-TTS / Piper streaming..."
                )
                # Fallback to Edge-TTS
                metadata["engine"] = "edge-tts"
                metadata["fallback"] = True
                ext = "mp3"
                media_type = "audio/mpeg"
                fallback_voice = self.edge_engine.get_default_voice_for_lang(resolved_lang)
                metadata["voice"] = fallback_voice

                try:
                    edge_accumulated: List[bytes] = []

                    async def raw_edge_generator():
                        stream = self.edge_engine.synthesize_stream(
                            text=clean_text, voice=fallback_voice, speed=speed
                        )
                        async for chunk in stream:
                            edge_accumulated.append(chunk)
                            yield chunk

                    edge_gen = raw_edge_generator()
                    first_edge_chunk = await edge_gen.__anext__()

                    async def wrapped_edge_generator():
                        yield first_edge_chunk
                        success = True
                        try:
                            async for ch in edge_gen:
                                yield ch
                        except Exception as edge_mid_err:
                            success = False
                            raise edge_mid_err
                        finally:
                            # Note: Never save emergency fallback audio to cache to avoid poisoning ElevenLabs cache
                            pass

                    return wrapped_edge_generator(), media_type, metadata

                except Exception as edge_err:
                    logger.warning(f"Edge-TTS fallback failed ({edge_err}), falling back to Piper...")
                    metadata["engine"] = "piper"
                    ext = "wav"
                    media_type = "audio/wav"
                    piper_voice = self.piper_engine.get_default_voice_for_lang(resolved_lang)
                    metadata["voice"] = piper_voice

                    async def piper_generator():
                        text_chunks = split_text_into_sentences(clean_text, max_chunk_chars=350)
                        collected = []
                        for ch in text_chunks:
                            b, _, _ = await self.piper_engine.synthesize(
                                text=ch, voice=piper_voice, speed=speed
                            )
                            collected.append(b)
                        full_wav = combine_wav_buffers(collected)
                        # Note: Never save emergency fallback audio to cache
                        for i in range(0, len(full_wav), 8192):
                            yield full_wav[i : i + 8192]
                            await asyncio.sleep(0)

                    return piper_generator(), media_type, metadata

        # 2. Explicit Edge-TTS stream request
        elif engine_name == "edge-tts":
            accumulated = []
            edge_fallback_occurred = False

            async def edge_stream_generator():
                nonlocal edge_fallback_occurred
                try:
                    stream = self.edge_engine.synthesize_stream(
                        text=clean_text, voice=resolved_voice, speed=speed
                    )
                    async for chunk in stream:
                        accumulated.append(chunk)
                        yield chunk
                except Exception as stream_err:
                    if not self.is_fallback_enabled():
                        raise stream_err
                    edge_fallback_occurred = True
                    logger.warning(f"Edge-TTS stream error ({stream_err}), falling back to Piper...")
                    fallback_audio, _, _ = await self.piper_engine.synthesize(
                        text=clean_text, voice=self.piper_engine.get_default_voice_for_lang(resolved_lang), speed=speed
                    )
                    accumulated.clear()
                    accumulated.append(fallback_audio)
                    for i in range(0, len(fallback_audio), 8192):
                        yield fallback_audio[i : i + 8192]
                finally:
                    # Only save if Edge-TTS itself produced the audio (never save Piper fallback into Edge-TTS cache)
                    if accumulated and not edge_fallback_occurred:
                        all_mp3 = b"".join(accumulated)
                        self.cache.save_cached_audio(cache_key, ext, all_mp3)

            return edge_stream_generator(), media_type, metadata

        # 3. Explicit Piper stream request
        else:
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
