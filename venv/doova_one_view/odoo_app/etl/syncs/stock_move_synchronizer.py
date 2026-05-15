"""
Stock move synchronizer
"""

import logging
import time
from typing import Tuple, List, Dict
from odoo_app.etl.syncs.base_synchronizer import BaseSynchronizer

logger = logging.getLogger(__name__)


class StockMoveSynchronizer(BaseSynchronizer):
    """Synchronizes stock.move and stock.move.line (inventory flows)"""

    def sync(self, tenant_id: str, last_sync_date: str = None, **kwargs) -> Tuple[int, int]:
        start_time = time.time()
        logger.info(f"Syncing stock moves for tenant {tenant_id}...")

        self.prefetch_ids('dim_products', tenant_id)
        self.prefetch_ids('dim_companies', tenant_id)
        self.prefetch_ids('dim_lots', tenant_id)
        self.prefetch_ids('fact_stock_pickings', tenant_id)

        domain = []
        if last_sync_date:
            domain.append(['write_date', '>', last_sync_date])

        try:
            move_fields = self.with_retry(self.odoo.get_fields, 'stock.move').keys()
            line_fields = self.with_retry(self.odoo.get_fields, 'stock.move.line').keys()
            
            req_move_fields = [
                'id', 'picking_id', 'product_id', 'company_id', 'location_id',
                'location_dest_id', 'product_uom_qty', 'quantity_done', 'date',
                'date_deadline', 'state', 'origin', 'reference', 'name', 'write_date'
            ]
            req_line_fields = [
                'id', 'move_id', 'product_id', 'lot_id', 'company_id',
                'location_id', 'location_dest_id', 'qty_done', 'product_uom_qty',
                'date', 'state', 'write_date'
            ]
            
            move_fields_avail = [f for f in req_move_fields if f in move_fields]
            line_fields_avail = [f for f in req_line_fields if f in line_fields]

            synced, failed = 0, 0
            
            move_query = """
                INSERT INTO fact_stock_moves (
                    tenant_id, odoo_id, odoo_picking_id, picking_id, product_id, company_id,
                    location_src, location_dest, product_uom_qty, quantity_done,
                    date, date_id, date_deadline, state, origin, reference, name,
                    odoo_write_date, synced_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (tenant_id, odoo_id) DO UPDATE SET
                    quantity_done = EXCLUDED.quantity_done, state = EXCLUDED.state,
                    odoo_write_date = EXCLUDED.odoo_write_date, synced_at = NOW()
            """
            
            line_query = """
                INSERT INTO fact_stock_move_lines (
                    tenant_id, stock_move_id, odoo_id, odoo_move_id,
                    product_id, lot_id, company_id, location_src, location_dest,
                    qty_done, product_uom_qty, date, state, odoo_write_date, synced_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (tenant_id, odoo_id) DO UPDATE SET
                    qty_done = EXCLUDED.qty_done, state = EXCLUDED.state,
                    odoo_write_date = EXCLUDED.odoo_write_date, synced_at = NOW()
            """

            move_batch = []
            move_odoo_ids = []
            
            for move in self.fetch_paginated('stock.move', domain, move_fields_avail):
                try:
                    odoo_picking_id = self.transformer.parse_odoo_many2one(move.get('picking_id'))
                    picking_id = self.get_internal_id('fact_stock_pickings', tenant_id, odoo_picking_id)
                    product_id = self.get_internal_id('dim_products', tenant_id, self.transformer.parse_odoo_many2one(move.get('product_id')))
                    company_id = self.get_internal_id('dim_companies', tenant_id, self.transformer.parse_odoo_many2one(move.get('company_id')))
                    
                    loc_src = move.get('location_id')[1] if isinstance(move.get('location_id'), (list, tuple)) else None
                    loc_dest = move.get('location_dest_id')[1] if isinstance(move.get('location_dest_id'), (list, tuple)) else None

                    move_batch.append((
                        tenant_id, move['id'], odoo_picking_id, picking_id, product_id, company_id,
                        loc_src, loc_dest,
                        self.transformer.parse_odoo_decimal(move.get('product_uom_qty', 0)),
                        self.transformer.parse_odoo_decimal(move.get('quantity_done', 0)),
                        self.transformer.parse_odoo_datetime(move.get('date')),
                        self.transformer.get_date_id(move.get('date')),
                        self.transformer.parse_odoo_date(move.get('date_deadline')),
                        move.get('state'), move.get('origin'), move.get('reference'), move.get('name'),
                        self.transformer.parse_odoo_datetime(move.get('write_date'))
                    ))
                    move_odoo_ids.append(move['id'])

                    if len(move_batch) >= 200:
                        self.execute_upsert_batch(move_query, move_batch)
                        synced += len(move_batch)
                        
                        # Sync lines for these moves
                        self._sync_move_lines(tenant_id, move_odoo_ids, line_fields_avail, line_query)
                        
                        move_batch = []
                        move_odoo_ids = []

                except Exception as e:
                    self.log_sync_error('stock.move', move['id'], e)
                    failed += 1

            if move_batch:
                self.execute_upsert_batch(move_query, move_batch)
                synced += len(move_batch)
                self._sync_move_lines(tenant_id, move_odoo_ids, line_fields_avail, line_query)

            self.log_sync_performance('stock.move', start_time, synced)
            return synced, failed

        except Exception as e:
            logger.error(f"Stock move sync failed: {e}")
            raise

    def _sync_move_lines(self, tenant_id: str, move_odoo_ids: List[int], fields: List[str], query: str):
        if not move_odoo_ids:
            return

        line_batch = []
        for line in self.fetch_paginated('stock.move.line', [['move_id', 'in', move_odoo_ids]], fields):
            try:
                odoo_move_id = self.transformer.parse_odoo_many2one(line.get('move_id'))
                stock_move_id = self.get_internal_id('fact_stock_moves', tenant_id, odoo_move_id)
                product_id = self.get_internal_id('dim_products', tenant_id, self.transformer.parse_odoo_many2one(line.get('product_id')))
                lot_id = self.get_internal_id('dim_lots', tenant_id, self.transformer.parse_odoo_many2one(line.get('lot_id')))
                company_id = self.get_internal_id('dim_companies', tenant_id, self.transformer.parse_odoo_many2one(line.get('company_id')))
                
                loc_src = line.get('location_id')[1] if isinstance(line.get('location_id'), (list, tuple)) else None
                loc_dest = line.get('location_dest_id')[1] if isinstance(line.get('location_dest_id'), (list, tuple)) else None

                line_batch.append((
                    tenant_id, stock_move_id, line['id'], odoo_move_id,
                    product_id, lot_id, company_id, loc_src, loc_dest,
                    self.transformer.parse_odoo_decimal(line.get('qty_done', 0)),
                    self.transformer.parse_odoo_decimal(line.get('product_uom_qty', 0)),
                    self.transformer.parse_odoo_datetime(line.get('date')),
                    line.get('state'),
                    self.transformer.parse_odoo_datetime(line.get('write_date'))
                ))

                if len(line_batch) >= 500:
                    self.execute_upsert_batch(query, line_batch)
                    line_batch = []

            except Exception:
                pass # Skip individual line errors

        if line_batch:
            self.execute_upsert_batch(query, line_batch)
