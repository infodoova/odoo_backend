"""
Background synchronization job
"""

import asyncio
import logging
from datetime import datetime
from django.db import close_old_connections
from odoo_app.models.tenant import Tenant
from doova_one_view.api.tenants.service import TenantService
from doova_one_view.api.config import settings
from doova_one_view.api.common.utils import db_sync_to_async

logger = logging.getLogger(__name__)

class SyncJobManager:
    """Manages background synchronization tasks"""
    
    _task: asyncio.Task = None
    _running: bool = False

    @classmethod
    async def start(cls):
        """Start the background sync loop"""
        if cls._running:
            return
            
        cls._running = True
        cls._task = asyncio.create_task(cls._run_loop())
        logger.info(f"Background Sync Job started. Interval: {settings.sync_interval_minutes} minutes")

    @classmethod
    async def stop(cls):
        """Stop the background sync loop"""
        cls._running = False
        if cls._task:
            cls._task.cancel()
            try:
                await cls._task
            except asyncio.CancelledError:
                pass
        logger.info("Background Sync Job stopped")

    @classmethod
    async def _run_loop(cls):
        """Internal execution loop"""
        while cls._running:
            try:
                close_old_connections()
                logger.info(f"Starting scheduled sync run at {datetime.now()}")
                await cls.run_sync_for_all_tenants()
                logger.info(f"Scheduled sync run completed. Sleeping for {settings.sync_interval_minutes} minutes.")
            except Exception as e:
                logger.error(f"Error in background sync loop: {e}")
            
            # Sleep in small increments to allow for faster shutdown
            for _ in range(settings.sync_interval_minutes * 60):
                if not cls._running:
                    break
                await asyncio.sleep(1)

    @staticmethod
    async def run_sync_for_all_tenants():
        """Execute smart sync for every active tenant"""
        close_old_connections()
        @db_sync_to_async
        def _get_active_tenants():
            return list(Tenant.objects.filter(is_active=True))
            
        tenants = await _get_active_tenants()
        
        for tenant in tenants:
            try:
                logger.info(f"Auto-syncing tenant: {tenant.name} ({tenant.id})")
                # run_smart_sync handles internal locking and full/delta logic
                await TenantService.run_smart_sync(str(tenant.id))
            except Exception as e:
                logger.error(f"Failed to auto-sync tenant {tenant.name}: {e}")
