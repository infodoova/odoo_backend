"""
Audio cache manager for Text-To-Speech (TTS).
Caches synthesized audio on disk to provide sub-millisecond responses for repeated phrases.
Includes automated TTL expiration (14 days), LRU capacity limits (2,500 files / 500 MB), and metrics.
"""

import os
import time
import hashlib
import logging
from pathlib import Path
from typing import Optional, Tuple, Dict, Any
from django.conf import settings

from doova_one_view.api.config import settings as api_settings

logger = logging.getLogger(__name__)


class TTSCacheManager:
    """
    Manages local filesystem caching for synthesized speech audio with lifecycle enforcement.
    """
    def __init__(self, cache_dir: Optional[Path] = None):
        if cache_dir is None:
            base_dir = getattr(settings, "BASE_DIR", Path(__file__).resolve().parents[4])
            self.cache_dir = Path(base_dir) / "storage_uploads" / "tts_cache"
        else:
            self.cache_dir = Path(cache_dir)

        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.default_max_age_days: int = getattr(api_settings, "tts_cache_max_age_days", 14)
        self.default_max_files: int = getattr(api_settings, "tts_cache_max_files", 2500)
        self.default_max_size_mb: int = getattr(api_settings, "tts_cache_max_size_mb", 500)
        self._last_expired_check: float = 0.0

    def generate_key(self, engine: str, voice: str, speed: float, text: str) -> str:
        """
        Creates a deterministic SHA-256 hash key for given parameters.
        Includes engine prefix (e.g. 'elevenlabs_abc123') to guarantee 100% isolation between engines.
        """
        clean_engine = "".join(c for c in (engine or "tts").lower() if c.isalnum()) or "tts"
        raw = f"{clean_engine}:{voice.strip()}:{speed:.2f}:{text.strip()}"
        hash_str = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        return f"{clean_engine}_{hash_str}"

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

    def get_cache_stats(self) -> Dict[str, Any]:
        """
        Returns disk usage and file metrics for the TTS voice cache.
        """
        files = list(self.cache_dir.glob("*.*"))
        total_files = len(files)
        total_bytes = 0
        oldest_mtime = None
        newest_mtime = None
        now = time.time()

        for p in files:
            try:
                st = p.stat()
                total_bytes += st.st_size
                if oldest_mtime is None or st.st_mtime < oldest_mtime:
                    oldest_mtime = st.st_mtime
                if newest_mtime is None or st.st_mtime > newest_mtime:
                    newest_mtime = st.st_mtime
            except Exception:
                pass

        oldest_age_days = round((now - oldest_mtime) / 86400.0, 2) if oldest_mtime else None
        newest_age_hours = round((now - newest_mtime) / 3600.0, 2) if newest_mtime else None

        return {
            "total_files": total_files,
            "total_size_bytes": total_bytes,
            "total_size_mb": round(total_bytes / (1024 * 1024), 2),
            "oldest_file_age_days": oldest_age_days,
            "newest_file_age_hours": newest_age_hours,
            "policy": {
                "max_age_days": self.default_max_age_days,
                "max_files": self.default_max_files,
                "max_size_mb": self.default_max_size_mb,
            }
        }

    def prune_expired_voices(self, max_age_days: Optional[int] = None) -> Dict[str, Any]:
        """
        Evicts cached voice files older than max_age_days (defaults to 14 days).
        If max_age_days is 0, evicts all cached files.
        """
        age_days = self.default_max_age_days if max_age_days is None else max_age_days
        now = time.time()
        cutoff = now - (age_days * 86400) if age_days > 0 else float("inf")

        deleted_files = 0
        freed_bytes = 0

        try:
            for p in self.cache_dir.glob("*.*"):
                try:
                    st = p.stat()
                    if age_days == 0 or st.st_mtime < cutoff:
                        file_size = st.st_size
                        p.unlink(missing_ok=True)
                        deleted_files += 1
                        freed_bytes += file_size
                except Exception as e:
                    logger.debug(f"Error removing expired cache file {p}: {e}")
        except Exception as e:
            logger.error(f"Error during expired voice cache pruning: {e}")

        remaining_files = len(list(self.cache_dir.glob("*.*")))
        if deleted_files > 0:
            logger.info(
                f"TTS Cache pruned expired voices (> {age_days}d): "
                f"deleted {deleted_files} files, freed {freed_bytes / (1024 * 1024):.2f} MB, {remaining_files} remaining."
            )

        return {
            "deleted_files": deleted_files,
            "freed_bytes": freed_bytes,
            "freed_mb": round(freed_bytes / (1024 * 1024), 2),
            "remaining_files": remaining_files,
        }

    def prune_by_capacity(
        self,
        max_size_mb: Optional[int] = None,
        max_files: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Enforces maximum cache capacity and file counts using LRU (oldest mtime first).
        Reduces cache to 80% of limit upon breach to prevent frequent churn.
        """
        size_limit_mb = self.default_max_size_mb if max_size_mb is None else max_size_mb
        files_limit = self.default_max_files if max_files is None else max_files
        size_limit_bytes = size_limit_mb * 1024 * 1024

        deleted_files = 0
        freed_bytes = 0

        try:
            file_entries = []
            total_bytes = 0
            for p in self.cache_dir.glob("*.*"):
                try:
                    st = p.stat()
                    file_entries.append((p, st.st_size, st.st_mtime))
                    total_bytes += st.st_size
                except Exception:
                    pass

            target_bytes = max(1, int(size_limit_bytes * 0.8)) if size_limit_bytes > 0 else 0
            target_files = max(1, int(files_limit * 0.8)) if files_limit > 0 else 0

            if len(file_entries) > files_limit or total_bytes > size_limit_bytes:
                # Sort ascending by mtime (oldest first)
                file_entries.sort(key=lambda item: item[2])

                for p, sz, _ in file_entries:
                    if len(file_entries) - deleted_files <= target_files and total_bytes - freed_bytes <= target_bytes:
                        break
                    try:
                        p.unlink(missing_ok=True)
                        deleted_files += 1
                        freed_bytes += sz
                    except Exception:
                        pass

        except Exception as e:
            logger.debug(f"Error during capacity-based voice cache pruning: {e}")

        remaining_files = len(list(self.cache_dir.glob("*.*")))
        return {
            "deleted_files": deleted_files,
            "freed_bytes": freed_bytes,
            "freed_mb": round(freed_bytes / (1024 * 1024), 2),
            "remaining_files": remaining_files,
        }

    def clear_all_cache(self) -> Dict[str, Any]:
        """
        Purges all cached audio files immediately.
        """
        return self.prune_expired_voices(max_age_days=0)

    def save_cached_audio(self, cache_key: str, ext: str, audio_bytes: bytes) -> Optional[Path]:
        """
        Saves audio bytes to cache file after ensuring capacity limits and TTL expiration.
        """
        if not audio_bytes:
            return None

        # Periodically purge files older than max_age_days (e.g. 14 days)
        now = time.time()
        if now - self._last_expired_check > 21600:  # 6 hours
            self._last_expired_check = now
            try:
                self.prune_expired_voices()
            except Exception as e:
                logger.debug(f"TTL check error: {e}")

        # Enforce LRU file count & 500 MB capacity ceiling
        self.prune_by_capacity()
        file_path = self.cache_dir / f"{cache_key}.{ext}"
        try:
            with open(file_path, "wb") as f:
                f.write(audio_bytes)
            return file_path
        except Exception as e:
            logger.warning(f"Failed to write TTS cache file {file_path}: {e}")
            return None
