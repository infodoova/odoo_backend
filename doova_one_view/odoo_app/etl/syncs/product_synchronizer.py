"""
Product dimension synchronizer (includes categories)
"""

import logging
import time
from typing import Tuple
from odoo_app.etl.syncs.base_synchronizer import BaseSynchronizer

logger = logging.getLogger(__name__)


class ProductCategorySynchronizer(BaseSynchronizer):
    """Synchronizes product.category"""

    def sync(self, tenant_id: str, last_sync_date: str = None, **kwargs) -> Tuple[int, int]:
        logger.info("Syncing product categories...")

        domain = []
        if last_sync_date:
            domain.append(['write_date', '>', last_sync_date])

        try:
            # Dynamically check for available fields (retriable)
            model_fields = self.with_retry(self.odoo.get_fields, 'product.category').keys()
            requested_fields = ['id', 'name', 'parent_id', 'complete_name', 'write_date']
            available_fields = [f for f in requested_fields if f in model_fields]

            synced, failed = 0, 0
            all_records = []

            # Use paginated fetcher
            for category in self.fetch_paginated('product.category', domain, available_fields):
                all_records.append(category)
                try:
                    query = """
                        INSERT INTO dim_product_categories (
                            tenant_id, odoo_id, name, complete_name
                        )
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (tenant_id, odoo_id)
                        DO UPDATE SET
                            name = EXCLUDED.name,
                            complete_name = EXCLUDED.complete_name
                    """

                    self.db.execute(query, (
                        tenant_id,
                        category['id'],
                        category['name'],
                        category.get('complete_name', category['name'])
                    ))

                    synced += 1

                except Exception as e:
                    self.log_sync_error('product.category', category['id'], e)
                    failed += 1

            self.db.conn.commit()

            # Second pass (parent updates) - usually fast so we don't paginate again
            for category in all_records:
                parent_odoo_id = self.transformer.parse_odoo_many2one(category.get('parent_id'))
                if parent_odoo_id:
                    try:
                        query = """
                            UPDATE dim_product_categories
                            SET parent_id = (
                                SELECT id FROM dim_product_categories
                                WHERE tenant_id = %s AND odoo_id = %s
                            )
                            WHERE tenant_id = %s AND odoo_id = %s
                        """
                        self.db.execute(query, (tenant_id, parent_odoo_id, tenant_id, category['id']))
                    except Exception:
                        pass # Non-critical error for parent links

            self.db.conn.commit()
            logger.info(f"Synced {synced} product categories, {failed} failed")
            return synced, failed

        except Exception as e:
            logger.error(f"Product category sync failed: {e}")
            raise


class ProductSynchronizer(BaseSynchronizer):
    """Synchronizes product.product"""

    def sync(self, tenant_id: str, last_sync_date: str = None, **kwargs) -> Tuple[int, int]:
        start_time = time.time()
        logger.info("Syncing products with batch optimization...")

        domain = [['active', 'in', [True, False]]]
        if last_sync_date:
            domain.append(['write_date', '>', last_sync_date])

        try:
            # Pre-fetch categories for fast lookup
            self.prefetch_ids('dim_product_categories', tenant_id)
            
            # Dynamically check for available fields (retriable)
            model_fields = self.with_retry(self.odoo.get_fields, 'product.product').keys()
            requested_fields = [
                'id', 'name', 'default_code', 'barcode', 'type',
                'categ_id', 'list_price', 'standard_price',
                'uom_id', 'active', 'product_tmpl_id', 'write_date'
            ]
            available_fields = [f for f in requested_fields if f in model_fields]

            synced, failed = 0, 0
            batch_params = []
            
            query = """
                INSERT INTO dim_products (
                    tenant_id, odoo_id, odoo_template_id,
                    name, default_code, barcode,
                    product_type, category_id,
                    list_price, standard_price,
                    uom_name, is_active,
                    created_at
                )
                VALUES (
                    %s, %s, %s,
                    %s, %s, %s,
                    %s, %s,
                    %s, %s,
                    %s, %s,
                    NOW()
                )
                ON CONFLICT (tenant_id, odoo_id)
                DO UPDATE SET
                    name = EXCLUDED.name,
                    default_code = EXCLUDED.default_code,
                    barcode = EXCLUDED.barcode,
                    list_price = EXCLUDED.list_price,
                    standard_price = EXCLUDED.standard_price,
                    is_active = EXCLUDED.is_active
            """

            # Use paginated fetcher
            for product in self.fetch_paginated('product.product', domain, available_fields):
                try:
                    category_odoo_id = self.transformer.parse_odoo_many2one(product.get('categ_id'))
                    category_id = self.get_internal_id('dim_product_categories', tenant_id, category_odoo_id)

                    batch_params.append((
                        tenant_id,
                        product['id'],
                        self.transformer.parse_odoo_many2one(product.get('product_tmpl_id')),
                        product['name'],
                        product.get('default_code'),
                        product.get('barcode'),
                        product.get('type', 'consu'),
                        category_id,
                        self.transformer.parse_odoo_decimal(product.get('list_price', 0)),
                        self.transformer.parse_odoo_decimal(product.get('standard_price', 0)),
                        None,
                        self.transformer.parse_odoo_boolean(product.get('active', True))
                    ))

                    if len(batch_params) >= 500:
                        synced += self.execute_upsert_batch(query, batch_params)
                        batch_params = []

                except Exception as e:
                    self.log_sync_error('product.product', product['id'], e)
                    failed += 1

            if batch_params:
                synced += self.execute_upsert_batch(query, batch_params)

            self.log_sync_performance('product.product', start_time, synced)
            return synced, failed

        except Exception as e:
            logger.error(f"Product sync failed: {e}")
            raise
