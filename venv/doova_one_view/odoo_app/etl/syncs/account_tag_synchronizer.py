"""
Account Tag dimension synchronizer (account.account.tag)
"""

import logging
import time
from typing import Tuple, List
from odoo_app.etl.syncs.base_synchronizer import BaseSynchronizer

logger = logging.getLogger(__name__)


class AccountTagSynchronizer(BaseSynchronizer):
    """Synchronizes account.account.tag (dimension table)"""

    def sync(self, tenant_id: str, last_sync_date: str = None, **kwargs) -> Tuple[int, int]:
        start_time = time.time()
        logger.info(f"Starting account.account.tag sync for tenant {tenant_id}")

        self.prefetch_ids('dim_companies', tenant_id)

        domain = []
        if last_sync_date:
            domain.append(['write_date', '>', last_sync_date])

        try:
            fields_avail = self.with_retry(self.odoo.get_fields, 'account.account.tag').keys()
            req_fields = [
                'id', 'name', 'applicability', 'color', 'tax_negate',
                'company_id', 'country_id', 'write_date'
            ]
            fields = [f for f in req_fields if f in fields_avail]

            generator = self.fetch_paginated('account.account.tag', domain, fields)

            query = """
                INSERT INTO dim_account_tags (
                    tenant_id, odoo_id,
                    name, applicability, color, tax_negate,
                    country_name, company_id,
                    odoo_write_date, synced_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (tenant_id, odoo_id) DO UPDATE SET
                    name = EXCLUDED.name,
                    applicability = EXCLUDED.applicability,
                    color = EXCLUDED.color,
                    tax_negate = EXCLUDED.tax_negate,
                    country_name = EXCLUDED.country_name,
                    company_id = EXCLUDED.company_id,
                    odoo_write_date = EXCLUDED.odoo_write_date,
                    synced_at = NOW()
            """

            params = []
            synced, failed = 0, 0

            for r in generator:
                try:
                    company_id = self.get_internal_id(
                        'dim_companies', tenant_id,
                        self.transformer.parse_odoo_many2one(r.get('company_id'))
                    )
                    country_name = None
                    c_data = r.get('country_id')
                    if isinstance(c_data, (list, tuple)) and len(c_data) > 1:
                        country_name = c_data[1]

                    params.append((
                        tenant_id,
                        r['id'],
                        r.get('name') or '',
                        r.get('applicability'),
                        r.get('color'),
                        bool(r.get('tax_negate', False)),
                        country_name,
                        company_id,
                        self.transformer.parse_odoo_datetime(r.get('write_date'))
                    ))

                    if len(params) >= 1000:
                        self.execute_upsert_batch(query, params)
                        synced += len(params)
                        params.clear()
                except Exception as e:
                    logger.error(f"Error processing account tag {r.get('id')}: {e}")
                    failed += 1

            if params:
                self.execute_upsert_batch(query, params)
                synced += len(params)
                params.clear()

            self.db.conn.commit()

            elapsed = time.time() - start_time
            rate = synced / elapsed if elapsed > 0 else 0
            logger.info(f"[account.account.tag] Sync complete: {synced} records in {elapsed:.2f}s ({rate:.2f} rec/s)")

            return synced, failed

        except Exception as e:
            logger.error(f"Account Tag sync failed: {e}")
            raise e
