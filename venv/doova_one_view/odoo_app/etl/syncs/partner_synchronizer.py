"""
Partner dimension synchronizer
"""

import logging
import time
from typing import Tuple
from odoo_app.etl.syncs.base_synchronizer import BaseSynchronizer

logger = logging.getLogger(__name__)


class PartnerSynchronizer(BaseSynchronizer):
    """Synchronizes res.partner"""

    def sync(self, tenant_id: str, last_sync_date: str = None, **kwargs) -> Tuple[int, int]:
        start_time = time.time()
        logger.info("Syncing partners with batch optimization...")

        domain = [['active', 'in', [True, False]]]
        if last_sync_date:
            domain.append(['write_date', '>', last_sync_date])

        try:
            # Dynamically check for available fields (retriable)
            model_fields = self.with_retry(self.odoo.get_fields, 'res.partner').keys()
            requested_fields = [
                'id', 'name', 'type', 'customer_rank', 'supplier_rank',
                'email', 'phone', 'country_id', 'city', 'company_id', 'write_date'
            ]
            available_fields = [f for f in requested_fields if f in model_fields]

            # Pre-fetch companies for fast lookup
            self.prefetch_ids('dim_companies', tenant_id)

            synced, failed = 0, 0
            batch_params = []
            
            query = """
                INSERT INTO dim_partners (
                    tenant_id, odoo_id, name, partner_type,
                    is_customer, is_supplier,
                    email, phone, country_code, city,
                    customer_rank, supplier_rank, is_active,
                    company_id, created_at
                )
                VALUES (
                    %s, %s, %s, %s,
                    %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, NOW()
                )
                ON CONFLICT (tenant_id, odoo_id)
                DO UPDATE SET
                    name = EXCLUDED.name,
                    email = EXCLUDED.email,
                    phone = EXCLUDED.phone,
                    customer_rank = EXCLUDED.customer_rank,
                    supplier_rank = EXCLUDED.supplier_rank,
                    company_id = EXCLUDED.company_id
            """

            # Use paginated fetcher
            for partner in self.fetch_paginated('res.partner', domain, available_fields):
                try:
                    customer_rank = partner.get('customer_rank', 0)
                    supplier_rank = partner.get('supplier_rank', 0)

                    batch_params.append((
                        tenant_id,
                        partner['id'],
                        partner['name'],
                        partner.get('type', 'contact'),
                        customer_rank > 0,
                        supplier_rank > 0,
                        partner.get('email'),
                        partner.get('phone'),
                        None,
                        partner.get('city'),
                        customer_rank,
                        supplier_rank,
                        True,
                        self.get_internal_id(
                            'dim_companies', tenant_id,
                            self.transformer.parse_odoo_many2one(partner.get('company_id'))
                        ),
                    ))

                    if len(batch_params) >= 500:
                        synced += self.execute_upsert_batch(query, batch_params)
                        batch_params = []

                except Exception as e:
                    self.log_sync_error('res.partner', partner['id'], e)
                    failed += 1

            if batch_params:
                synced += self.execute_upsert_batch(query, batch_params)

            self.log_sync_performance('res.partner', start_time, synced)
            return synced, failed

        except Exception as e:
            logger.error(f"Partner sync failed: {e}")
            raise
