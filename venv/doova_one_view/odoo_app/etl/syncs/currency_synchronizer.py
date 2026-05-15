"""
Fix 2 of 2 — updated CurrencySynchronizer
(odoo_app/etl/syncs/currency_synchronizer.py)

Changes:
  - Collects all rows into params_list then calls execute_upsert_batch()
    instead of calling self.db.execute_query() per row (which didn't exist).
  - execute_upsert_batch() is already defined on BaseSynchronizer and calls
    self.db.execute_batch() — consistent with every other synchronizer.
  - Wraps the whole run in log_sync_performance() for monitoring.
"""

import logging
import time
from typing import Tuple

from odoo_app.etl.syncs.base_synchronizer import BaseSynchronizer

logger = logging.getLogger(__name__)


class CurrencySynchronizer(BaseSynchronizer):
    """Synchronizes res.currency → dim_currencies"""

    UPSERT_SQL = """
        INSERT INTO dim_currencies (
            tenant_id, odoo_id, code, symbol, is_active,
            symbol_position, rounding, odoo_write_date, synced_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
        ON CONFLICT (tenant_id, odoo_id) DO UPDATE SET
            code             = EXCLUDED.code,
            symbol           = EXCLUDED.symbol,
            is_active        = EXCLUDED.is_active,
            symbol_position  = EXCLUDED.symbol_position,
            rounding         = EXCLUDED.rounding,
            odoo_write_date  = EXCLUDED.odoo_write_date,
            synced_at        = NOW()
    """

    REQUESTED_FIELDS = [
        'id', 'name', 'symbol', 'active',
        'position', 'rounding', 'write_date',
    ]

    def sync(self, tenant_id: str, last_sync_date: str = None, **kwargs) -> Tuple[int, int]:
        """
        Sync currencies from Odoo → dim_currencies.

        Args:
            tenant_id:      Tenant UUID
            last_sync_date: ISO timestamp — when set, only changed records are fetched

        Returns:
            (synced_count, failed_count)
        """
        logger.info(f"[CurrencySynchronizer] Starting — tenant={tenant_id}")
        start = time.time()

        # ── 1. Build domain ────────────────────────────────────────────────
        domain = []
        if last_sync_date:
            domain.append(['write_date', '>', last_sync_date])

        # ── 2. Resolve available fields (handles different Odoo versions) ──
        model_fields = self.with_retry(self.odoo.get_fields, 'res.currency').keys()
        available_fields = [f for f in self.REQUESTED_FIELDS if f in model_fields]
        logger.debug(f"[CurrencySynchronizer] Fetching fields: {available_fields}")

        # ── 3. Collect rows ────────────────────────────────────────────────
        params_list = []
        failed = 0

        for currency in self.fetch_paginated('res.currency', domain, available_fields):
            try:
                params_list.append(self._build_params(tenant_id, currency))
            except Exception as e:
                logger.error(
                    f"[CurrencySynchronizer] Failed to build params "
                    f"for currency {currency.get('id')}: {e}"
                )
                failed += 1

        # ── 4. Bulk upsert ─────────────────────────────────────────────────
        synced = 0
        if params_list:
            try:
                synced = self.execute_upsert_batch(self.UPSERT_SQL, params_list)
            except Exception as e:
                logger.error(f"[CurrencySynchronizer] Batch upsert failed: {e}")
                failed += len(params_list)

        # ── 5. Log performance ─────────────────────────────────────────────
        self.log_sync_performance('res.currency', start, synced)
        logger.info(
            f"[CurrencySynchronizer] Done — {synced} synced, {failed} failed"
        )
        return synced, failed

    # ── Private helpers ────────────────────────────────────────────────────

    def _build_params(self, tenant_id: str, currency: dict) -> tuple:
        """
        Map a raw Odoo res.currency record to the dim_currencies insert tuple.

        Odoo field → DB column:
            name     → code          (e.g. 'USD', 'EUR')
            symbol   → symbol        (e.g. '$', '€')
            active   → is_active
            position → symbol_position ('before' | 'after')
            rounding → rounding      (e.g. 0.010000)
        """
        return (
            tenant_id,
            currency['id'],                                                    # odoo_id
            currency.get('name'),                                              # code
            currency.get('symbol'),                                            # symbol
            currency.get('active', True),                                      # is_active
            currency.get('position', 'after'),                                 # symbol_position
            self.transformer.parse_odoo_decimal(currency.get('rounding', 0.01)),  # rounding
            self.transformer.parse_odoo_datetime(currency.get('write_date')), # odoo_write_date
        )