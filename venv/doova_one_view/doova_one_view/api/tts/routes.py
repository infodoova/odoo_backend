"""
FastAPI Routes for Text-To-Speech (TTS) subsystem.
Provides streaming synthesis and voice catalog endpoints.
"""

import logging
from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse
from typing import Optional

from doova_one_view.api.tts.schemas import TTSRequest, VoiceListResponse
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
