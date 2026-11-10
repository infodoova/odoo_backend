"""
Stock lot synchronizer
"""

import logging
import time
from typing import Tuple, List, Dict
from odoo_app.etl.syncs.base_synchronizer import BaseSynchronizer

logger = logging.getLogger(__name__)


class LotSynchronizer(BaseSynchronizer):
    """Synchronizes stock.lot (lot/serial dimension)"""

    def sync(self, tenant_id: str, last_sync_date: str = None, **kwargs) -> Tuple[int, int]:
        start_time = time.time()
        logger.info("Syncing inventory lots with batch optimization...")

        domain = []
        if last_sync_date:
            domain.append(['write_date', '>', last_sync_date])

        try:
            # Check if user has read permission on stock.lot to avoid crashing or unnecessary retries
            try:
                has_access = self.odoo.call_kw('stock.lot', 'check_access_rights', ['read', False])
            except Exception:
                has_access = True  # Fallback to standard flow if check_access_rights call fails

            if has_access is False:
                logger.warning(
                    f"Skipping stock.lot sync for tenant {tenant_id}: User lacks read permission on 'stock.lot'. "
                    "Lot tracking is optional; lot references in inventory moves and quants will default to NULL."
                )
                return 0, 0

            # Pre-fetch for fast lookups
            self.prefetch_ids('dim_products', tenant_id)
            self.prefetch_ids('dim_companies', tenant_id)
            
            # Dynamically check for available fields (retriable)
            model_fields = self.with_retry(self.odoo.get_fields, 'stock.lot').keys()
            requested_fields = [
                'id', 'name', 'ref', 'product_id', 'company_id',
                'expiration_date', 'use_date', 'removal_date', 'alert_date',
                'write_date'
            ]
            available_fields = [f for f in requested_fields if f in model_fields]

            synced, failed = 0, 0
            batch_params = []
            
            query = """
                INSERT INTO dim_lots (
                    tenant_id, odoo_id, product_id, company_id,
                    name, ref, expiration_date, use_date,
                    removal_date, alert_date, odoo_write_date,
                    synced_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (tenant_id, odoo_id)
                DO UPDATE SET
                    product_id = EXCLUDED.product_id,
                    company_id = EXCLUDED.company_id,
                    name = EXCLUDED.name,
                    ref = EXCLUDED.ref,
                    expiration_date = EXCLUDED.expiration_date,
                    use_date = EXCLUDED.use_date,
                    removal_date = EXCLUDED.removal_date,
                    alert_date = EXCLUDED.alert_date,
                    odoo_write_date = EXCLUDED.odoo_write_date,
                    synced_at = NOW()
            """

            # Use paginated fetcher
            for lot in self.fetch_paginated('stock.lot', domain, available_fields):
                try:
                    product_id = self.get_internal_id(
                        'dim_products',
                        tenant_id,
                        self.transformer.parse_odoo_many2one(lot.get('product_id'))
                    )
                    company_id = self.get_internal_id(
                        'dim_companies',
                        tenant_id,
                        self.transformer.parse_odoo_many2one(lot.get('company_id'))
                    )

                    batch_params.append((
                        tenant_id,
                        lot['id'],
                        product_id,
                        company_id,
                        lot['name'],
                        lot.get('ref'),
                        self.transformer.parse_odoo_date(lot.get('expiration_date')),
                        self.transformer.parse_odoo_date(lot.get('use_date')),
                        self.transformer.parse_odoo_date(lot.get('removal_date')),
                        self.transformer.parse_odoo_date(lot.get('alert_date')),
                        self.transformer.parse_odoo_datetime(lot.get('write_date'))
                    ))

                    if len(batch_params) >= 500:
                        synced += self.execute_upsert_batch(query, batch_params)
                        batch_params = []

                except Exception as e:
                    self.log_sync_error('stock.lot', lot['id'], e)
                    failed += 1

            if batch_params:
                synced += self.execute_upsert_batch(query, batch_params)

            self.log_sync_performance('stock.lot', start_time, synced)
            return synced, failed

        except Exception as e:
            err_str = str(e).lower()
            if any(k in err_str for k in ["not allowed to access", "accessdenied", "accesserror", "access denied"]):
                logger.warning(
                    f"Skipping stock.lot sync for tenant {tenant_id}: User lacks read permission ({e}). "
                    "Lot tracking is optional; lot references in inventory moves and quants will default to NULL."
                )
                return 0, 0
            logger.error(f"Lot sync failed: {e}")
            raise
