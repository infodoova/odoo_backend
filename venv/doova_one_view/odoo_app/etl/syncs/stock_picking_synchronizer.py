"""
Stock picking synchronizer
"""

import logging
import time
from typing import Tuple, List, Dict
from odoo_app.etl.syncs.base_synchronizer import BaseSynchronizer

logger = logging.getLogger(__name__)


class StockPickingSynchronizer(BaseSynchronizer):
    """Synchronizes stock.picking (inventory pickings)"""

    def sync(self, tenant_id: str, last_sync_date: str = None, **kwargs) -> Tuple[int, int]:
        start_time = time.time()
        logger.info(f"Syncing stock pickings for tenant {tenant_id}...")

        self.prefetch_ids('dim_partners', tenant_id)
        self.prefetch_ids('dim_companies', tenant_id)

        domain = []
        if last_sync_date:
            domain.append(['write_date', '>', last_sync_date])

        try:
            model_fields = self.with_retry(self.odoo.get_fields, 'stock.picking').keys()
            req_fields = [
                'id', 'name', 'partner_id', 'company_id', 'scheduled_date',
                'date_done', 'picking_type_id', 'state', 'origin', 'create_date', 'write_date'
            ]
            available_fields = [f for f in req_fields if f in model_fields]

            synced, failed = 0, 0
            batch_params = []
            
            query = """
                INSERT INTO fact_stock_pickings (
                    tenant_id, odoo_id, odoo_name, partner_id, company_id,
                    scheduled_date, scheduled_date_id, date_done, date_done_id,
                    picking_type, state, origin, odoo_create_date, odoo_write_date, synced_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (tenant_id, odoo_id) DO UPDATE SET
                    state = EXCLUDED.state, date_done = EXCLUDED.date_done,
                    odoo_create_date = EXCLUDED.odoo_create_date,
                    odoo_write_date = EXCLUDED.odoo_write_date, synced_at = NOW()
            """

            for picking in self.fetch_paginated('stock.picking', domain, available_fields):
                try:
                    partner_id = self.get_internal_id('dim_partners', tenant_id, self.transformer.parse_odoo_many2one(picking.get('partner_id')))
                    company_id = self.get_internal_id('dim_companies', tenant_id, self.transformer.parse_odoo_many2one(picking.get('company_id')))
                    
                    picking_type_data = picking.get('picking_type_id')
                    picking_type = picking_type_data[1] if isinstance(picking_type_data, (list, tuple)) else None

                    batch_params.append((
                        tenant_id, picking['id'], picking.get('name'), partner_id, company_id,
                        self.transformer.parse_odoo_datetime(picking.get('scheduled_date')),
                        self.transformer.get_date_id(picking.get('scheduled_date')),
                        self.transformer.parse_odoo_datetime(picking.get('date_done')),
                        self.transformer.get_date_id(picking.get('date_done')),
                        picking_type, picking.get('state'), picking.get('origin'),
                        self.transformer.parse_odoo_datetime(picking.get('create_date')),
                        self.transformer.parse_odoo_datetime(picking.get('write_date'))
                    ))

                    if len(batch_params) >= 500:
                        synced += self.execute_upsert_batch(query, batch_params)
                        batch_params = []

                except Exception as e:
                    self.log_sync_error('stock.picking', picking['id'], e)
                    failed += 1

            if batch_params:
                synced += self.execute_upsert_batch(query, batch_params)

            self.log_sync_performance('stock.picking', start_time, synced)
            return synced, failed

        except Exception as e:
            logger.error(f"Stock picking sync failed: {e}")
            raise
