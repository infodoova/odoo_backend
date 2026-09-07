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


class TTSCachePolicy(BaseModel):
    max_age_days: int = Field(..., description="Configured maximum retention age in days (TTL)")
    max_files: int = Field(..., description="Configured maximum number of cached audio files")
    max_size_mb: int = Field(..., description="Configured maximum total cache size in megabytes")


class TTSCacheStatsResponse(BaseModel):
    total_files: int = Field(..., description="Current count of cached audio files")
    total_size_bytes: int = Field(..., description="Total cache size in bytes")
    total_size_mb: float = Field(..., description="Total cache size in megabytes")
    oldest_file_age_days: Optional[float] = Field(None, description="Age in days of the oldest cached file")
    newest_file_age_hours: Optional[float] = Field(None, description="Age in hours of the most recently written file")
    policy: TTSCachePolicy = Field(..., description="Active cache limits and retention policies")


class TTSCacheCleanResponse(BaseModel):
    deleted_files: int = Field(..., description="Number of audio files purged during cleanup")
    freed_bytes: int = Field(..., description="Disk space freed in bytes")
    freed_mb: float = Field(..., description="Disk space freed in megabytes")
    remaining_files: int = Field(..., description="Remaining count of cached audio files")
    message: str = Field(..., description="Summary message of the clean operation")

