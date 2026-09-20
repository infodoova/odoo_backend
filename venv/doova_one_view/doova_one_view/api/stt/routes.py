"""
FastAPI Routes for Speech-To-Text (STT) powered by Deepgram Nova-3 Multilingual.
"""

import logging
from typing import Optional
from fastapi import APIRouter, File, UploadFile, Query, Request, HTTPException, Form, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from doova_one_view.api.stt.service import stt_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/stt", tags=["Speech-To-Text"])


class STTResponse(BaseModel):
    transcript: str = Field(..., description="Transcribed text")
    language: str = Field(..., description="Detected or requested language code (e.g. 'ar', 'en', 'fr', 'es')")
    confidence: float = Field(0.0, description="Transcription confidence score")


@router.get(
    "/token",
    summary="Get STT streaming connection credentials",
    description="Returns ephemeral configuration for STT live streaming."
)
async def get_stt_token():
    key = stt_service.api_key
    if not key:
        raise HTTPException(status_code=500, detail="DEEPGRAM_API_KEY is not configured on the server.")
    return {"token": key}


@router.websocket("/live")
async def live_stt(
    websocket: WebSocket,
    language: Optional[str] = Query("auto", description="Target language: 'auto', 'ar', 'en', 'fr', 'es'"),
    encoding: Optional[str] = Query("linear16", description="Audio encoding: 'linear16' or 'webm'"),
    sample_rate: Optional[int] = Query(16000, description="Audio sample rate in Hz"),
):
    """
    Bidirectional WebSocket endpoint for zero-latency live Speech-To-Text streaming.
    Streams microphone audio chunks and emits real-time interim & final transcripts
    with dual-stream Arabic/Multilingual arbitration.
    """
    await websocket.accept()
    if not stt_service.api_key:
        await websocket.send_json({"type": "error", "message": "DEEPGRAM_API_KEY is not configured on the server."})
        await websocket.close()
        return

    session = stt_service.create_live_session(
        language=language or "auto",
        encoding=encoding or "linear16",
        sample_rate=sample_rate or 16000
    )
    try:
        await session.stream_socket(websocket)
    except WebSocketDisconnect:
        session.is_closed = True
    except Exception as e:
        logger.warning(f"Live STT socket session ended: {e}")
    finally:
        session.is_closed = True
        try:
            await websocket.close()
        except Exception:
            pass


@router.post(
    "/transcribe",
    response_model=STTResponse,
    summary="Transcribe spoken audio via Deepgram Nova-3 Multilingual",
    description="Accepts audio binary data or multipart upload and returns the transcribed text with detected language."
)
async def transcribe_audio(
    request: Request,
    file: Optional[UploadFile] = File(None),
    language: Optional[str] = Query("auto", description="Target language: 'auto', 'ar', 'en', 'fr', 'es'"),
):
    try:
        audio_bytes = b""
        content_type = "audio/webm"

        if file:
            audio_bytes = await file.read()
            content_type = file.content_type or "audio/webm"
        else:
            audio_bytes = await request.body()
            content_type = request.headers.get("content-type") or "audio/webm"

        if not audio_bytes or len(audio_bytes) < 100:
            return STTResponse(transcript="", language=language or "en", confidence=0.0)

        result = await stt_service.transcribe(
            audio_bytes=audio_bytes,
            content_type=content_type,
            language=language or "auto",
        )

        return STTResponse(
            transcript=result["transcript"],
            language=result["language"],
            confidence=result.get("confidence", 0.0),
        )

    except ValueError as ve:
        logger.error(f"STT validation error: {ve}")
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        logger.error(f"STT transcription error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Speech-to-Text transcription failed: {str(e)}")

