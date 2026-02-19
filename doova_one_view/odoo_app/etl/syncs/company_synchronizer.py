"""
Company dimension synchronizer
"""

import logging
from typing import Tuple
from odoo_app.etl.syncs.base_synchronizer import BaseSynchronizer

logger = logging.getLogger(__name__)


class CompanySynchronizer(BaseSynchronizer):
    """Synchronizes res.company (company dimension)"""

    def sync(self, tenant_id: str, last_sync_date: str = None, **kwargs) -> Tuple[int, int]:
        logger.info("Syncing companies...")

        domain = []
        if last_sync_date:
            domain.append(['write_date', '>', last_sync_date])

        try:
            # Dynamically check for available fields (retriable)
            model_fields = self.with_retry(self.odoo.get_fields, 'res.company').keys()
            requested_fields = ['id', 'name', 'currency_id', 'country_id', 'write_date']
            available_fields = [f for f in requested_fields if f in model_fields]

            synced, failed = 0, 0

            # Use paginated fetcher
            for company in self.fetch_paginated('res.company', domain, available_fields):
                try:
                    query = """
                        INSERT INTO dim_companies (
                            tenant_id, odoo_id, name,
                            currency_code, country_code, is_active,
                            created_at
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, NOW())
                        ON CONFLICT (tenant_id, odoo_id)
                        DO UPDATE SET
                            name = EXCLUDED.name,
                            currency_code = EXCLUDED.currency_code,
                            country_code = EXCLUDED.country_code,
                            is_active = EXCLUDED.is_active
                    """

                    self.db.execute(query, (
                        tenant_id,
                        company['id'],
                        company['name'],
                        None,
                        None,
                        True
                    ))

                    synced += 1

                except Exception as e:
                    self.log_sync_error('res.company', company['id'], e)
                    failed += 1

            self.db.conn.commit()
            logger.info(f"Synced {synced} companies, {failed} failed")
            return synced, failed

        except Exception as e:
            logger.error(f"Company sync failed: {e}")
            raise
