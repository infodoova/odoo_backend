"""
Pydantic schemas for Text-To-Speech (TTS) module.
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Literal


class TTSRequest(BaseModel):
    text: str = Field(..., min_length=1, description="Text to synthesize into speech (unlimited length with progressive sentence chunking)")
    lang: Optional[str] = Field(
        default="auto",
        description="Target language ('auto', 'en', 'fr', 'es', 'ar'). Defaults to 'auto' for auto-detection."
    )
    voice: Optional[str] = Field(
        default=None,
        description="Specific voice model/name to use. If omitted, a high-quality default for the language is selected."
    )
    speed: Optional[float] = Field(
        default=1.0,
        ge=0.5,
        le=2.0,
        description="Speech playback speed multiplier (0.5 to 2.0). Default is 1.0."
    )


class VoiceInfo(BaseModel):
    id: str = Field(..., description="Unique voice identifier")
    name: str = Field(..., description="Human-readable voice name")
    language: str = Field(..., description="Language code (en, fr, es, ar)")
    language_name: str = Field(..., description="Language display name")
    gender: Literal["male", "female", "neutral"] = Field(..., description="Voice gender")
    engine: Literal["piper", "edge-tts"] = Field(..., description="Underlying TTS engine")
    is_default: bool = Field(default=False, description="Whether this is the default voice for its language")


class VoiceListResponse(BaseModel):
    voices: List[VoiceInfo]
    engines: List[str]
    languages: List[str]
