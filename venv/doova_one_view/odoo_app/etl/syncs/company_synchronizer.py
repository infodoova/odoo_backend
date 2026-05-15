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
            # Dynamically check for available fields
            model_fields = self.with_retry(self.odoo.get_fields, 'res.company').keys()
            requested_fields = ['id', 'name', 'display_name', 'currency_id', 'country_id', 'active', 'write_date']
            available_fields = [f for f in requested_fields if f in model_fields]

            synced, failed = 0, 0

            # Use paginated fetcher
            for company in self.fetch_paginated('res.company', domain, available_fields):
                try:
                    # Extract Many2one fields
                    currency_data = company.get('currency_id')
                    currency_id = None
                    currency_name = None
                    if isinstance(currency_data, (list, tuple)) and len(currency_data) >= 2:
                        currency_id = currency_data[0]
                        currency_name = currency_data[1]

                    country_data = company.get('country_id')
                    country_id = None
                    country_name = None
                    if isinstance(country_data, (list, tuple)) and len(country_data) >= 2:
                        country_id = country_data[0]
                        country_name = country_data[1]

                    # Parse dates and booleans
                    odoo_write_date = self.transformer.parse_odoo_datetime(company.get('write_date'))
                    is_active = self.transformer.parse_odoo_boolean(company.get('active')) if 'active' in company else True

                    query = """
                        INSERT INTO dim_companies (
                            tenant_id, odoo_id, name, display_name,
                            currency_id, currency_name, currency_code,
                            country_id, country_name, country_code,
                            is_active, odoo_write_date, created_at
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                        ON CONFLICT (tenant_id, odoo_id)
                        DO UPDATE SET
                            name = EXCLUDED.name,
                            display_name = EXCLUDED.display_name,
                            currency_id = EXCLUDED.currency_id,
                            currency_name = EXCLUDED.currency_name,
                            currency_code = EXCLUDED.currency_code,
                            country_id = EXCLUDED.country_id,
                            country_name = EXCLUDED.country_name,
                            country_code = EXCLUDED.country_code,
                            is_active = EXCLUDED.is_active,
                            odoo_write_date = EXCLUDED.odoo_write_date
                    """

                    self.db.execute(query, (
                        tenant_id,
                        company['id'],
                        company['name'],
                        company.get('display_name', company['name']),
                        currency_id,
                        currency_name,
                        currency_name,  # Using name as code fallback
                        country_id,
                        country_name,
                        None,  # Country code usually not in res.company directly without extra fetch
                        is_active,
                        odoo_write_date
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
