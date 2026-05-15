"""
Purchase fact table synchronizer
"""

import logging
import time
from typing import Tuple, List, Dict
from odoo_app.etl.syncs.base_synchronizer import BaseSynchronizer

logger = logging.getLogger(__name__)


class PurchaseOrderSynchronizer(BaseSynchronizer):
    """Synchronizes purchase.order and purchase.order.line (purchase fact tables)"""
    
    def sync(self, tenant_id: str, last_sync_date: str = None, **kwargs) -> Tuple[int, int]:
        """
        High-performance batch sync for purchase orders and lines.
        """
        start_time = time.time()
        logger.info(f"Starting purchase batch sync for tenant {tenant_id}")
        
        # Pre-fetch dimensions for fast lookup
        self.prefetch_ids('dim_partners', tenant_id)
        self.prefetch_ids('dim_users', tenant_id)
        self.prefetch_ids('dim_companies', tenant_id)
        self.prefetch_ids('dim_products', tenant_id)
        
        domain = []
        if last_sync_date:
            domain.append(['write_date', '>', last_sync_date])
        
        try:
            # 1. Prepare Metadata
            order_fields = self.with_retry(self.odoo.get_fields, 'purchase.order').keys()
            line_fields = self.with_retry(self.odoo.get_fields, 'purchase.order.line').keys()
            
            req_order_fields = [
                'id', 'name', 'partner_id', 'user_id', 'company_id', 'date_order', 'date_planned',
                'date_approve', 'state', 'invoice_status', 'amount_untaxed',
                'amount_tax', 'amount_total', 'currency_id', 'partner_ref', 'write_date'
            ]
            req_line_fields = [
                'id', 'order_id', 'product_id', 'product_qty', 'qty_received',
                'qty_invoiced', 'price_unit', 'price_subtotal', 'price_total',
                'date_planned', 'name', 'company_id', 'write_date'
            ]
            
            order_fields_avail = [f for f in req_order_fields if f in order_fields]
            line_fields_avail = [f for f in req_line_fields if f in line_fields]
            
            synced, failed = 0, 0
            
            # 2. Process in Batches
            batch_size = 200
            order_generator = self.fetch_paginated(
                model='purchase.order',
                domain=domain,
                fields=order_fields_avail,
                batch_size=batch_size
            )
            
            current_batch = []
            for order in order_generator:
                current_batch.append(order)
                
                if len(current_batch) >= batch_size:
                    s, f = self._process_order_batch(tenant_id, current_batch, line_fields_avail)
                    synced += s
                    failed += f
                    current_batch = []
            
            # Final batch
            if current_batch:
                s, f = self._process_order_batch(tenant_id, current_batch, line_fields_avail)
                synced += s
                failed += f
            
            self.log_sync_performance('purchase.order', start_time, synced)
            return synced, failed
            
        except Exception as e:
            logger.error(f"Purchase sync failed: {e}")
            raise

    def _process_order_batch(self, tenant_id: str, orders: List[dict], line_fields: List[str]) -> Tuple[int, int]:
        """
        Process a batch of purchase orders and their lines.
        """
        order_params = []
        order_odoo_ids = []
        
        for order in orders:
            try:
                partner_id = self.get_internal_id('dim_partners', tenant_id, self.transformer.parse_odoo_many2one(order.get('partner_id')))
                user_id = self.get_internal_id('dim_users', tenant_id, self.transformer.parse_odoo_many2one(order.get('user_id')))
                company_id = self.get_internal_id('dim_companies', tenant_id, self.transformer.parse_odoo_many2one(order.get('company_id')))
                
                currency_data = order.get('currency_id')
                currency_code = currency_data[1] if isinstance(currency_data, (list, tuple)) else None

                order_params.append((
                    tenant_id, order['id'], order.get('name'), company_id, partner_id, user_id,
                    self.transformer.parse_odoo_datetime(order.get('date_order')),
                    self.transformer.get_date_id(order.get('date_order')),
                    self.transformer.parse_odoo_datetime(order.get('date_planned')),
                    self.transformer.parse_odoo_datetime(order.get('date_approve')),
                    order.get('state'), order.get('invoice_status'),
                    self.transformer.parse_odoo_decimal(order.get('amount_untaxed', 0)),
                    self.transformer.parse_odoo_decimal(order.get('amount_tax', 0)),
                    self.transformer.parse_odoo_decimal(order.get('amount_total', 0)),
                    currency_code, order.get('partner_ref'),
                    self.transformer.parse_odoo_datetime(order.get('write_date'))
                ))
                order_odoo_ids.append(order['id'])
            except Exception as e:
                logger.error(f"Error preparing purchase order {order.get('id')}: {e}")

        # 1. Batch Upsert Orders
        order_query = """
            INSERT INTO fact_purchase_orders (
                tenant_id, odoo_id, odoo_name, company_id, partner_id, user_id,
                date_order, date_order_id, date_planned, date_approve,
                state, invoice_status, amount_untaxed, amount_tax, amount_total,
                currency_code, partner_ref, odoo_write_date, synced_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (tenant_id, odoo_id) DO UPDATE SET 
                state = EXCLUDED.state, invoice_status = EXCLUDED.invoice_status,
                amount_total = EXCLUDED.amount_total, odoo_write_date = EXCLUDED.odoo_write_date,
                synced_at = NOW()
        """
        self.execute_upsert_batch(order_query, order_params)
        order_params.clear()

        # 2. Bulk Fetch All Lines
        line_query = """
            INSERT INTO fact_purchase_order_lines (
                tenant_id, purchase_order_id, odoo_id, odoo_order_id,
                product_id, company_id, product_qty, qty_received,
                qty_invoiced, price_unit, price_subtotal, price_total,
                date_planned, name, odoo_write_date, synced_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (tenant_id, odoo_id) DO UPDATE SET 
                qty_received = EXCLUDED.qty_received, qty_invoiced = EXCLUDED.qty_invoiced,
                price_subtotal = EXCLUDED.price_subtotal, odoo_write_date = EXCLUDED.odoo_write_date,
                synced_at = NOW()
        """
        
        line_params = []
        line_generator = self.fetch_paginated(
            'purchase.order.line',
            domain=[['order_id', 'in', order_odoo_ids]],
            fields=line_fields
        )

        for line in line_generator:
            try:
                order_odoo_id = self.transformer.parse_odoo_many2one(line.get('order_id'))
                purchase_order_id = self.get_internal_id('fact_purchase_orders', tenant_id, order_odoo_id)
                
                product_id = self.get_internal_id('dim_products', tenant_id, self.transformer.parse_odoo_many2one(line.get('product_id')))
                company_id = self.get_internal_id('dim_companies', tenant_id, self.transformer.parse_odoo_many2one(line.get('company_id')))
                
                line_params.append((
                    tenant_id, purchase_order_id, line['id'], order_odoo_id, product_id, company_id,
                    self.transformer.parse_odoo_decimal(line.get('product_qty', 0)),
                    self.transformer.parse_odoo_decimal(line.get('qty_received', 0)),
                    self.transformer.parse_odoo_decimal(line.get('qty_invoiced', 0)),
                    self.transformer.parse_odoo_decimal(line.get('price_unit', 0)),
                    self.transformer.parse_odoo_decimal(line.get('price_subtotal', 0)),
                    self.transformer.parse_odoo_decimal(line.get('price_total', 0)),
                    self.transformer.parse_odoo_datetime(line.get('date_planned')),
                    line.get('name'),
                    self.transformer.parse_odoo_datetime(line.get('write_date'))
                ))

                if len(line_params) >= 1000:
                    self.execute_upsert_batch(line_query, line_params)
                    line_params.clear()

            except Exception as e:
                logger.error(f"Error preparing purchase line {line.get('id')}: {e}")

        if line_params:
            self.execute_upsert_batch(line_query, line_params)
            line_params.clear()
        
        return len(orders), 0
