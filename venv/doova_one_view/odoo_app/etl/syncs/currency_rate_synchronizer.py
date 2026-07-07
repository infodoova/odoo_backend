"""
CurrencyRateSynchronizer
Syncs res.currency.rate from Odoo into dim_currency_rates.

Each record represents a daily exchange rate for a given currency,
relative to the company's base currency.
"""

import logging
import time
from typing import Tuple

from odoo_app.etl.syncs.base_synchronizer import BaseSynchronizer

logger = logging.getLogger(__name__)


class CurrencyRateSynchronizer(BaseSynchronizer):
    """Synchronizes res.currency.rate -> dim_currency_rates"""

    UPSERT_SQL = """
        INSERT INTO dim_currency_rates (
            tenant_id, odoo_id, currency_id, company_id, name, rate,
            odoo_write_date, synced_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
        ON CONFLICT (tenant_id, odoo_id) DO UPDATE SET
            currency_id     = EXCLUDED.currency_id,
            company_id      = EXCLUDED.company_id,
            name            = EXCLUDED.name,
            rate            = EXCLUDED.rate,
            odoo_write_date = EXCLUDED.odoo_write_date,
            synced_at       = NOW()
    """

    # SQL to resolve Odoo currency ID -> our dim_currencies.id
    CURRENCY_LOOKUP_SQL = """
        SELECT id, odoo_id FROM dim_currencies WHERE tenant_id = %s
    """

    # SQL to resolve Odoo company ID -> our dim_companies.id
    COMPANY_LOOKUP_SQL = """
        SELECT id, odoo_id FROM dim_companies WHERE tenant_id = %s
    """

    REQUESTED_FIELDS = [
        'id', 'name', 'rate', 'currency_id', 'company_id', 'write_date',
    ]

    def sync(self, tenant_id: str, last_sync_date: str = None, **kwargs) -> Tuple[int, int]:
        """
        Sync currency rates from Odoo -> dim_currency_rates.

        Args:
            tenant_id:      Tenant UUID
            last_sync_date: ISO timestamp - when set, only changed records are fetched

        Returns:
            (synced_count, failed_count)
        """
        logger.info(f"[CurrencyRateSynchronizer] Starting - tenant={tenant_id}")
        start = time.time()

        # 1. Build domain
        domain = []
        if last_sync_date:
            domain.append(['write_date', '>', last_sync_date])

        # 2. Resolve available fields
        model_fields = self.with_retry(self.odoo.get_fields, 'res.currency.rate').keys()
        available_fields = [f for f in self.REQUESTED_FIELDS if f in model_fields]
        logger.debug(f"[CurrencyRateSynchronizer] Fetching fields: {available_fields}")

        # 3. Build local lookup maps: odoo_id -> local db id
        currency_map = {}
        company_map = {}
        try:
            rows = self.db.fetch_all(self.CURRENCY_LOOKUP_SQL, (tenant_id,))
            currency_map = {row[1]: row[0] for row in rows}
            logger.info(f"[CurrencyRateSynchronizer] Loaded {len(currency_map)} currencies for lookup")
        except Exception as e:
            logger.warning(f"[CurrencyRateSynchronizer] Could not load currency map: {e}")

        try:
            rows = self.db.fetch_all(self.COMPANY_LOOKUP_SQL, (tenant_id,))
            company_map = {row[1]: row[0] for row in rows}
            logger.info(f"[CurrencyRateSynchronizer] Loaded {len(company_map)} companies for lookup")
        except Exception as e:
            logger.warning(f"[CurrencyRateSynchronizer] Could not load company map: {e}")

        # 4. Collect rows
        params_list = []
        failed = 0

        for rate_record in self.fetch_paginated('res.currency.rate', domain, available_fields):
            try:
                params = self._build_params(tenant_id, rate_record, currency_map, company_map)
                if params:
                    params_list.append(params)
            except Exception as e:
                logger.error(
                    f"[CurrencyRateSynchronizer] Failed to build params "
                    f"for rate {rate_record.get('id')}: {e}"
                )
                failed += 1

        # 5. Bulk upsert
        synced = 0
        if params_list:
            try:
                synced = self.execute_upsert_batch(self.UPSERT_SQL, params_list)
            except Exception as e:
                logger.error(f"[CurrencyRateSynchronizer] Batch upsert failed: {e}")
                failed += len(params_list)

        # 6. Log performance
        self.log_sync_performance('res.currency.rate', start, synced)
        logger.info(
            f"[CurrencyRateSynchronizer] Done - {synced} synced, {failed} failed"
        )
        return synced, failed

    def _build_params(self, tenant_id: str, rate: dict, currency_map: dict, company_map: dict) -> tuple:
        """
        Map a raw Odoo res.currency.rate record to the dim_currency_rates insert tuple.

        Odoo field -> DB column:
            name        -> name          (date string e.g. '2026-07-07')
            rate        -> rate          (e.g. 1.085000)
            currency_id -> currency_id   (FK to dim_currencies)
            company_id  -> company_id    (FK to dim_companies, nullable)
        """
        # Resolve currency FK
        raw_currency = rate.get('currency_id')
        odoo_currency_id = raw_currency[0] if isinstance(raw_currency, (list, tuple)) else raw_currency
        local_currency_id = currency_map.get(odoo_currency_id)

        if not local_currency_id:
            logger.debug(f"[CurrencyRateSynchronizer] Skipping rate {rate['id']}: currency {odoo_currency_id} not in local DB")
            return None

        # Resolve company FK (optional)
        raw_company = rate.get('company_id')
        odoo_company_id = raw_company[0] if isinstance(raw_company, (list, tuple)) else raw_company
        local_company_id = company_map.get(odoo_company_id) if odoo_company_id else None

        return (
            tenant_id,
            rate['id'],                                                     # odoo_id
            local_currency_id,                                              # currency_id (FK)
            local_company_id,                                               # company_id (FK, nullable)
            rate.get('name'),                                               # name (date)
            self.transformer.parse_odoo_decimal(rate.get('rate', 1.0), decimal_places=6), # rate
            self.transformer.parse_odoo_datetime(rate.get('write_date')),   # odoo_write_date
        )
