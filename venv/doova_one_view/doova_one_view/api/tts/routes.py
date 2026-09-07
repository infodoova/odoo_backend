"""
FastAPI Routes for Text-To-Speech (TTS) subsystem.
Provides streaming synthesis and voice catalog endpoints.
"""

import logging
from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse
from typing import Optional

from doova_one_view.api.tts.schemas import (
    TTSRequest,
    VoiceListResponse,
    TTSCacheStatsResponse,
    TTSCacheCleanResponse,
)
from doova_one_view.api.tts.service import tts_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tts", tags=["Text-To-Speech"])


@router.get(
    "/voices",
    response_model=VoiceListResponse,
    summary="List available TTS voices",
    description="Returns all supported voices across Piper (EN, FR, ES) and Edge-TTS (AR) engines."
)
async def get_voices():
    """Returns list of supported voices, languages, and engines."""
    return tts_service.get_available_voices()


@router.post(
    "/synthesize",
    summary="Synthesize speech (POST Streaming)",
    description="Synthesizes text into streaming audio. Supports English, French, Spanish (Piper), and Arabic (Edge-TTS)."
)
async def synthesize_speech_post(request: TTSRequest):
    """
    POST synthesis endpoint returning streaming audio.
    """
    if not request.text or not request.text.strip():
        raise HTTPException(status_code=400, detail="Text field cannot be empty.")

    try:
        stream_gen, media_type, meta = await tts_service.synthesize_stream(
            text=request.text,
            lang=request.lang,
            voice=request.voice,
            speed=request.speed or 1.0,
        )

        headers = {
            "Content-Type": media_type,
            "X-TTS-Engine": meta["engine"],
            "X-TTS-Language": meta["language"],
            "X-TTS-Voice": meta["voice"],
            "X-TTS-Cached": str(meta["cached"]).lower(),
            "Accept-Ranges": "bytes",
            "Cache-Control": "public, max-age=86400",
        }

        return StreamingResponse(stream_gen, media_type=media_type, headers=headers)

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"TTS synthesis error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"TTS synthesis failed: {str(e)}")


@router.get(
    "/synthesize",
    summary="Synthesize speech (GET Streaming)",
    description="GET synthesis endpoint for direct HTML5 <audio> tag playback or quick testing."
)
async def synthesize_speech_get(
    text: str = Query(..., min_length=1, description="Text to synthesize"),
    lang: Optional[str] = Query("auto", description="Language: 'auto', 'en', 'fr', 'es', 'ar'"),
    voice: Optional[str] = Query(None, description="Specific voice identifier"),
    speed: Optional[float] = Query(1.0, ge=0.5, le=2.0, description="Playback speed factor"),
):
    """
    GET synthesis endpoint returning streaming audio (ideal for <audio src="...">).
    """
    if not text or not text.strip():
        raise HTTPException(status_code=400, detail="Text parameter cannot be empty.")

    try:
        stream_gen, media_type, meta = await tts_service.synthesize_stream(
            text=text,
            lang=lang,
            voice=voice,
            speed=speed or 1.0,
        )

        headers = {
            "Content-Type": media_type,
            "X-TTS-Engine": meta["engine"],
            "X-TTS-Language": meta["language"],
            "X-TTS-Voice": meta["voice"],
            "X-TTS-Cached": str(meta["cached"]).lower(),
            "Accept-Ranges": "bytes",
            "Cache-Control": "public, max-age=86400",
        }

        return StreamingResponse(stream_gen, media_type=media_type, headers=headers)

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"TTS synthesis error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"TTS synthesis failed: {str(e)}")


@router.get(
    "/cache/stats",
    response_model=TTSCacheStatsResponse,
    summary="Get TTS audio cache statistics",
    description="Returns total files, disk usage in bytes/MB, oldest file age, and current retention policies."
)
async def get_cache_stats():
    """Returns disk and count metrics for the voice cache directory."""
    return tts_service.cache.get_cache_stats()


@router.post(
    "/cache/clean",
    response_model=TTSCacheCleanResponse,
    summary="Clean expired or excess TTS audio cache",
    description="Purges audio files older than max_age_days (default: 14) and enforces LRU file/size limits (default: 2,500 files, 500 MB)."
)
async def clean_cache(
    max_age_days: Optional[int] = Query(None, ge=0, description="Max age in days (defaults to 14, 0 = delete all)"),
    max_files: Optional[int] = Query(None, ge=1, description="Max cache files allowed (defaults to 2500)"),
    max_size_mb: Optional[int] = Query(None, ge=1, description="Max cache size in MB (defaults to 500)"),
):
    """Executes TTL eviction and LRU capacity pruning on the TTS audio cache."""
    # Step 1: Purge expired by age
    expired_result = tts_service.cache.prune_expired_voices(max_age_days=max_age_days)
    # Step 2: Enforce capacity
    capacity_result = tts_service.cache.prune_by_capacity(max_size_mb=max_size_mb, max_files=max_files)

    total_deleted = expired_result["deleted_files"] + capacity_result["deleted_files"]
    total_freed_bytes = expired_result["freed_bytes"] + capacity_result["freed_bytes"]
    remaining = capacity_result["remaining_files"]

    return {
        "deleted_files": total_deleted,
        "freed_bytes": total_freed_bytes,
        "freed_mb": round(total_freed_bytes / (1024 * 1024), 2),
        "remaining_files": remaining,
        "message": f"Successfully cleaned TTS cache: {total_deleted} files removed, {round(total_freed_bytes / (1024 * 1024), 2)} MB freed."
    }


@router.delete(
    "/cache",
    response_model=TTSCacheCleanResponse,
    summary="Clear entire TTS audio cache",
    description="Instantly deletes all cached speech files from disk."
)
async def clear_cache():
    """Purges all files in the TTS audio cache."""
    result = tts_service.cache.clear_all_cache()
    return {
        "deleted_files": result["deleted_files"],
        "freed_bytes": result["freed_bytes"],
        "freed_mb": result["freed_mb"],
        "remaining_files": result["remaining_files"],
        "message": f"Successfully cleared all TTS cache: {result['deleted_files']} files removed, {result['freed_mb']} MB freed."
    }

