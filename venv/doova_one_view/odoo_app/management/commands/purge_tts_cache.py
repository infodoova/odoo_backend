"""
Django management command to inspect and purge expired or excess Text-To-Speech (TTS) audio files.
Enforces the 14-day max age policy and 2,500 file / 500 MB capacity limit.
"""

from django.core.management.base import BaseCommand
from doova_one_view.api.tts.cache import TTSCacheManager


class Command(BaseCommand):
    help = "Purge expired or excess TTS cached voice audio files."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=None,
            help="Purge voice files older than N days (default: configured 14 days, 0 = delete all).",
        )
        parser.add_argument(
            "--max-files",
            type=int,
            default=None,
            help="Maximum cache files to retain under LRU policy (default: 2500).",
        )
        parser.add_argument(
            "--max-size-mb",
            type=int,
            default=None,
            help="Maximum total cache size in MB to retain under LRU policy (default: 500 MB).",
        )
        parser.add_argument(
            "--all",
            action="store_true",
            help="Purge ALL cached voice files immediately regardless of age.",
        )
        parser.add_argument(
            "--stats",
            action="store_true",
            help="Display current TTS cache usage stats without deleting files.",
        )

    def handle(self, *args, **options):
        manager = TTSCacheManager()

        # Display current stats
        stats = manager.get_cache_stats()
        self.stdout.write(self.style.NOTICE("=== TTS Cache Status ==="))
        self.stdout.write(f"Location:           {manager.cache_dir}")
        self.stdout.write(f"Total Files:        {stats['total_files']:,}")
        self.stdout.write(f"Total Size:         {stats['total_size_mb']} MB ({stats['total_size_bytes']:,} bytes)")
        if stats["oldest_file_age_days"] is not None:
            self.stdout.write(f"Oldest File Age:    {stats['oldest_file_age_days']} days")
        if stats["newest_file_age_hours"] is not None:
            self.stdout.write(f"Newest File Age:    {stats['newest_file_age_hours']} hours")
        self.stdout.write(
            f"Policy Config:      TTL {stats['policy']['max_age_days']} days | "
            f"Max {stats['policy']['max_files']} files | "
            f"Max {stats['policy']['max_size_mb']} MB"
        )
        self.stdout.write("========================\n")

        if options["stats"]:
            return

        if options["all"]:
            self.stdout.write(self.style.WARNING("Purging ALL cached voice files..."))
            result = manager.clear_all_cache()
            self.stdout.write(
                self.style.SUCCESS(
                    f"Successfully cleared all cache: {result['deleted_files']} files deleted, "
                    f"{result['freed_mb']} MB freed. {result['remaining_files']} files remaining."
                )
            )
            return

        days = 0 if options["all"] else options["days"]
        max_files = options["max_files"]
        max_size_mb = options["max_size_mb"]

        effective_days = manager.default_max_age_days if days is None else days
        self.stdout.write(f"Pruning files older than {effective_days} days...")
        expired_result = manager.prune_expired_voices(max_age_days=days)
        self.stdout.write(
            f"  -> Expired sweep: {expired_result['deleted_files']} files deleted, "
            f"{expired_result['freed_mb']} MB freed."
        )

        self.stdout.write("Enforcing LRU capacity limits...")
        capacity_result = manager.prune_by_capacity(max_size_mb=max_size_mb, max_files=max_files)
        self.stdout.write(
            f"  -> Capacity sweep: {capacity_result['deleted_files']} files deleted, "
            f"{capacity_result['freed_mb']} MB freed."
        )

        total_deleted = expired_result["deleted_files"] + capacity_result["deleted_files"]
        total_freed_mb = round(expired_result["freed_mb"] + capacity_result["freed_mb"], 2)

        self.stdout.write(
            self.style.SUCCESS(
                f"\nTTS cache purge completed! Total deleted: {total_deleted} files, "
                f"{total_freed_mb} MB freed. Retained: {capacity_result['remaining_files']} files."
            )
        )
