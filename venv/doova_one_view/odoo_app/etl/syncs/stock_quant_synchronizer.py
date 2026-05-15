"""
Stock quant synchronizer
"""

import logging
import time
from typing import Tuple, List, Dict
from odoo_app.etl.syncs.base_synchronizer import BaseSynchronizer

logger = logging.getLogger(__name__)


class StockQuantSynchronizer(BaseSynchronizer):
    """Synchronizes stock.quant (real-time inventory levels)"""

    def sync(self, tenant_id: str, **kwargs) -> Tuple[int, int]:
        start_time = time.time()
        logger.info(f"Syncing stock quants for tenant {tenant_id}...")

        self.prefetch_ids('dim_products', tenant_id)
        self.prefetch_ids('dim_companies', tenant_id)
        self.prefetch_ids('dim_lots', tenant_id)

        try:
            model_fields = self.with_retry(self.odoo.get_fields, 'stock.quant').keys()
            req_fields = [
                'id', 'product_id', 'lot_id', 'company_id', 'location_id',
                'quantity', 'reserved_quantity', 'in_date', 'write_date'
            ]
            available_fields = [f for f in req_fields if f in model_fields]

            synced, failed = 0, 0
            batch_params = []
            
            query = """
                INSERT INTO fact_stock_quants (
                    tenant_id, odoo_id, product_id, lot_id, company_id,
                    location_name, quantity, reserved_quantity, in_date,
                    odoo_write_date, synced_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (tenant_id, odoo_id) DO UPDATE SET
                    quantity = EXCLUDED.quantity, 
                    reserved_quantity = EXCLUDED.reserved_quantity,
                    odoo_write_date = EXCLUDED.odoo_write_date, synced_at = NOW()
            """

            # Quants are usually synced in full because they are small and delta is tricky
            for quant in self.fetch_paginated('stock.quant', [], available_fields):
                try:
                    product_id = self.get_internal_id('dim_products', tenant_id, self.transformer.parse_odoo_many2one(quant.get('product_id')))
                    lot_id = self.get_internal_id('dim_lots', tenant_id, self.transformer.parse_odoo_many2one(quant.get('lot_id')))
                    company_id = self.get_internal_id('dim_companies', tenant_id, self.transformer.parse_odoo_many2one(quant.get('company_id')))
                    
                    loc_name = quant.get('location_id')[1] if isinstance(quant.get('location_id'), (list, tuple)) else None

                    batch_params.append((
                        tenant_id, quant['id'], product_id, lot_id, company_id,
                        loc_name,
                        self.transformer.parse_odoo_decimal(quant.get('quantity', 0)),
                        self.transformer.parse_odoo_decimal(quant.get('reserved_quantity', 0)),
                        self.transformer.parse_odoo_datetime(quant.get('in_date')),
                        self.transformer.parse_odoo_datetime(quant.get('write_date'))
                    ))

                    if len(batch_params) >= 500:
                        synced += self.execute_upsert_batch(query, batch_params)
                        batch_params = []

                except Exception as e:
                    self.log_sync_error('stock.quant', quant['id'], e)
                    failed += 1

            if batch_params:
                synced += self.execute_upsert_batch(query, batch_params)

            self.log_sync_performance('stock.quant', start_time, synced)
            return synced, failed

        except Exception as e:
            logger.error(f"Stock quant sync failed: {e}")
            raise
