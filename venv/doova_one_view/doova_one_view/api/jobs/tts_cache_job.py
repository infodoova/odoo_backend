"""
Background maintenance job for Text-To-Speech (TTS) audio cache.
Periodically purges voice files older than the configured TTL (14 days)
and enforces LRU capacity limits (2,500 files / 500 MB).
"""

import asyncio
import logging
from datetime import datetime

from doova_one_view.api.config import settings
from doova_one_view.api.tts.cache import TTSCacheManager

logger = logging.getLogger(__name__)


class TTSCacheJobManager:
    """Manages scheduled background cleanup for cached TTS audio files."""

    _task: asyncio.Task = None
    _running: bool = False

    @classmethod
    async def start(cls):
        """Start the background TTS cache cleanup loop."""
        if cls._running:
            return

        cls._running = True
        cls._task = asyncio.create_task(cls._run_loop())
        logger.info(
            f"TTS Cache Cleanup Job started. "
            f"Interval: {settings.tts_cache_cleanup_interval_hours} hours | "
            f"TTL: {settings.tts_cache_max_age_days} days | "
            f"Max Files: {settings.tts_cache_max_files}"
        )

    @classmethod
    async def stop(cls):
        """Stop the background cleanup loop gracefully."""
        cls._running = False
        if cls._task:
            cls._task.cancel()
            try:
                await cls._task
            except asyncio.CancelledError:
                pass
        logger.info("TTS Cache Cleanup Job stopped.")

    @classmethod
    async def _run_loop(cls):
        """Internal loop executing periodic cleanup sweeps."""
        # Optional initial pause to avoid delaying cold server bootstrap
        await asyncio.sleep(10)

        while cls._running:
            try:
                logger.info(f"Starting scheduled TTS cache pruning at {datetime.now()}")
                await asyncio.to_thread(cls.run_cleanup)
                logger.info("Scheduled TTS cache pruning cycle completed.")
            except Exception as e:
                logger.error(f"Error in TTS cache cleanup loop: {e}", exc_info=True)

            # Sleep in 1-second ticks for fast shutdown responsiveness
            sleep_seconds = int(settings.tts_cache_cleanup_interval_hours * 3600)
            for _ in range(sleep_seconds):
                if not cls._running:
                    break
                await asyncio.sleep(1)

    @staticmethod
    def run_cleanup():
        """Synchronous cleanup execution suitable for worker threads or direct invocation."""
        manager = TTSCacheManager()
        # 1. Purge expired voices older than 14 days
        expired = manager.prune_expired_voices()
        # 2. Enforce capacity limit (2,500 files, 500 MB)
        capacity = manager.prune_by_capacity()

        total_freed_mb = round((expired["freed_bytes"] + capacity["freed_bytes"]) / (1024 * 1024), 2)
        total_deleted = expired["deleted_files"] + capacity["deleted_files"]

        if total_deleted > 0:
            logger.info(
                f"TTS Cache Purge completed: {total_deleted} files deleted, "
                f"{total_freed_mb} MB reclaimed, {capacity['remaining_files']} files retained."
            )
        else:
            logger.debug(f"TTS Cache Purge: 0 files eligible for deletion ({capacity['remaining_files']} active files).")
