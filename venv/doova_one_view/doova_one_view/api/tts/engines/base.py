"""
Base abstract class for TTS engines.
"""

from abc import ABC, abstractmethod
from typing import AsyncGenerator, Tuple, List, Optional
from doova_one_view.api.tts.schemas import VoiceInfo


class BaseTTSEngine(ABC):
    """
    Abstract Base Class for Text-To-Speech engines.
    """

    @property
    @abstractmethod
    def engine_name(self) -> str:
        """Returns the engine identifier name ('piper' or 'edge-tts')."""
        pass

    @abstractmethod
    def get_supported_voices(self) -> List[VoiceInfo]:
        """Returns list of voices available for this engine."""
        pass

    @abstractmethod
    async def synthesize(
        self,
        text: str,
        voice: Optional[str] = None,
        speed: float = 1.0
    ) -> Tuple[bytes, str, str]:
        """
        Synthesizes text into full audio bytes.
        Returns: (audio_bytes, media_type, file_extension) e.g. (b'...', 'audio/wav', 'wav')
        """
        pass

    @abstractmethod
    async def synthesize_stream(
        self,
        text: str,
        voice: Optional[str] = None,
        speed: float = 1.0
    ) -> AsyncGenerator[bytes, None]:
        """
        Synthesizes text and yields audio chunks asynchronously.
        """
        pass
