"""
Audio cache manager for Text-To-Speech (TTS).
Caches synthesized audio on disk to provide sub-millisecond responses for repeated phrases.
"""

import os
import hashlib
import logging
from pathlib import Path
from typing import Optional, Tuple
from django.conf import settings

logger = logging.getLogger(__name__)


class TTSCacheManager:
    """
    Manages local filesystem caching for synthesized speech audio.
    """
    def __init__(self, cache_dir: Optional[Path] = None):
        if cache_dir is None:
            base_dir = getattr(settings, "BASE_DIR", Path(__file__).resolve().parents[4])
            self.cache_dir = Path(base_dir) / "storage_uploads" / "tts_cache"
        else:
            self.cache_dir = Path(cache_dir)

        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def generate_key(self, engine: str, voice: str, speed: float, text: str) -> str:
        """
        Creates a deterministic SHA-256 hash key for given parameters.
        """
        raw = f"{engine}:{voice}:{speed:.2f}:{text.strip()}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def get_cached_file(self, cache_key: str, ext: str) -> Optional[Path]:
        """
        Returns the Path to cached audio file if it exists and has content.
        """
        file_path = self.cache_dir / f"{cache_key}.{ext}"
        if file_path.exists() and file_path.stat().st_size > 0:
            return file_path
        return None

    def get_cached_bytes(self, cache_key: str, ext: str) -> Optional[bytes]:
        """
        Reads and returns cached audio bytes, or None if not found.
        """
        file_path = self.get_cached_file(cache_key, ext)
        if file_path:
            try:
                with open(file_path, "rb") as f:
                    return f.read()
            except Exception as e:
                logger.warning(f"Failed to read cached TTS file {file_path}: {e}")
        return None

    def _prune_cache_if_needed(self, max_files: int = 5000):
        """
        Maintains cache size limit to prevent unbounded disk growth.
        Evicts oldest files if total cached files exceed limit.
        """
        try:
            files = list(self.cache_dir.glob("*.*"))
            if len(files) > max_files:
                # Sort by modification time ascending (oldest first)
                files.sort(key=lambda p: p.stat().st_mtime)
                # Remove oldest 20% of files
                excess = len(files) - int(max_files * 0.8)
                for p in files[:excess]:
                    try:
                        p.unlink(missing_ok=True)
                    except Exception:
                        pass
        except Exception as e:
            logger.debug(f"Cache pruning error: {e}")

    def save_cached_audio(self, cache_key: str, ext: str, audio_bytes: bytes) -> Optional[Path]:
        """
        Saves audio bytes to cache file.
        """
        if not audio_bytes:
            return None
        self._prune_cache_if_needed()
        file_path = self.cache_dir / f"{cache_key}.{ext}"
        try:
            with open(file_path, "wb") as f:
                f.write(audio_bytes)
            return file_path
        except Exception as e:
            logger.warning(f"Failed to write TTS cache file {file_path}: {e}")
            return None
