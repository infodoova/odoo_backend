import logging
import time
from abc import ABC, abstractmethod
from typing import List, Dict, Optional, Tuple, Any, Callable
from functools import lru_cache

from odoo_app.etl.clients.odoo_client import OdooClient
from odoo_app.etl.managers.database_manager import DatabaseManager
from odoo_app.etl.transformers.data_transformer import DataTransformer

logger = logging.getLogger(__name__)


class BaseSynchronizer(ABC):
    """
    Abstract base class for all sync operations.
    Includes production-grade utilities for batching, caching, and retries.
    """
    
    def __init__(self, odoo_client: OdooClient, db_manager: DatabaseManager):
        self.odoo = odoo_client
        self.db = db_manager
        self.transformer = DataTransformer()
        
        # Performance: Cache internal IDs to avoid repeated lookups during a single sync run
        # Using a simple dict as a per-run cache
        self._id_cache = {}
    
    @abstractmethod
    def sync(self, tenant_id: str, **kwargs) -> Tuple[int, int]:
        """Execute synchronization"""
        pass
    
    def get_internal_id(
        self, 
        table: str, 
        tenant_id: str, 
        odoo_id: Optional[int]
    ) -> Optional[int]:
        """
        Get internal database ID for an Odoo record.
        Uses a per-run cache to minimize database hits.
        """
        if not odoo_id:
            return None
        
        cache_key = f"{table}:{tenant_id}:{odoo_id}"
        if cache_key in self._id_cache:
            return self._id_cache[cache_key]
        
        query = f"SELECT id FROM {table} WHERE tenant_id = %s AND odoo_id = %s"
        result = self.db.fetch_one(query, (tenant_id, odoo_id))
        
        internal_id = result[0] if result else None
        self._id_cache[cache_key] = internal_id
        return internal_id

    def fetch_paginated(
        self,
        model: str,
        domain: List,
        fields: List[str],
        batch_size: int = 1000,
        order: str = 'id asc'
    ):
        """
        Generator to fetch records in batches to handle large datasets.
        In production, never fetch everything at once.
        """
        offset = 0
        while True:
            records = self.odoo.search_read(
                model=model,
                domain=domain,
                fields=fields,
                limit=batch_size,
                offset=offset,
                order=order
            )
            
            if not records:
                break
                
            for record in records:
                yield record
                
            if len(records) < batch_size:
                break
                
            offset += batch_size

    def with_retry(self, func: Callable, *args, max_retries: int = 3, **kwargs) -> Any:
        """Helper to retry Odoo operations with exponential backoff"""
        last_exception = None
        for i in range(max_retries):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                last_exception = e
                wait = (2 ** i) + (0.1 * i)
                logger.warning(f"Retry {i+1}/{max_retries} following error: {e}. Waiting {wait:.1f}s")
                time.sleep(wait)
        
        raise last_exception

    def execute_upsert_batch(
        self, 
        query: str, 
        params_list: List[tuple], 
        batch_size: int = 500
    ) -> int:
        """
        Execute batch upsert for high performance.
        Reduces DB round-trips from N to (N / batch_size).
        """
        if not params_list:
            return 0
        
        try:
            self.db.execute_batch(query, params_list, page_size=batch_size)
            return len(params_list)
        except Exception as e:
            logger.error(f"Batch upsert failed: {e}")
            # In production, we might want to fallback to row-by-row if batch fails
            # to identify the specific bad record, but for speed, batch is king.
            raise

    def prefetch_ids(self, table: str, tenant_id: str, threshold: int = 50000):
        """
        Performance + Safety: Pre-fetch IDs only if the table size is safe for memory.
        If table > threshold, it falls back to on-demand caching.
        """
        # 1. Check count first to protect memory
        count_query = f"SELECT COUNT(*) FROM {table} WHERE tenant_id = %s"
        count_res = self.db.fetch_one(count_query, (tenant_id,))
        count = count_res[0] if count_res else 0
        
        if count > threshold:
            logger.warning(f"[{table}] Table too large for pre-fetch ({count} rows). Using on-demand caching for memory safety.")
            return

        if count == 0:
            return

        # 2. Safe to load
        logger.info(f"Pre-fetching {count} IDs for {table}...")
        query = f"SELECT odoo_id, id FROM {table} WHERE tenant_id = %s"
        results = self.db.fetch_all(query, (tenant_id,))
        
        for odoo_id, internal_id in results:
            cache_key = f"{table}:{tenant_id}:{odoo_id}"
            self._id_cache[cache_key] = internal_id
        
        logger.info(f"Cached {len(results)} IDs for {table}")

    def log_sync_performance(self, entity_type: str, start_time: float, count: int):
        """Log performance metrics for monitoring"""
        duration = time.time() - start_time
        rate = count / duration if duration > 0 else 0
        logger.info(f"[{entity_type}] Sync complete: {count} records in {duration:.2f}s ({rate:.2f} rec/s)")

    def clear_cache(self):
        """Clear the internal ID cache (usually between sync phases)"""
        self._id_cache = {}
