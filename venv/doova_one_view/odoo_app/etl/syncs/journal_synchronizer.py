"""
Journal dimension synchronizer
"""

import logging
import time
from typing import Tuple
from odoo_app.etl.syncs.base_synchronizer import BaseSynchronizer

logger = logging.getLogger(__name__)

class JournalSynchronizer(BaseSynchronizer):
    """Synchronizes account.journal (dimension table)"""
    
    def sync(self, tenant_id: str, last_sync_date: str = None, **kwargs) -> Tuple[int, int]:
        start_time = time.time()
        logger.info(f"Starting journal batch sync for tenant {tenant_id}")
        
        self.prefetch_ids('dim_companies', tenant_id)
        
        domain = []
        if last_sync_date:
            domain.append(['write_date', '>', last_sync_date])
            
        try:
            fields_avail = self.with_retry(self.odoo.get_fields, 'account.journal').keys()
            req_fields = ['id', 'name', 'code', 'type', 'currency_id', 'company_id', 'default_account_id', 'write_date']
            fields = [f for f in req_fields if f in fields_avail]
            
            generator = self.fetch_paginated('account.journal', domain, fields)
            
            query = """
                INSERT INTO dim_account_journals (
                    tenant_id, odoo_id,
                    name, code, type, currency_code, company_id,
                    default_account_id, default_account_code,
                    odoo_write_date, synced_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (tenant_id, odoo_id) DO UPDATE SET
                    name = EXCLUDED.name,
                    code = EXCLUDED.code,
                    type = EXCLUDED.type,
                    currency_code = EXCLUDED.currency_code,
                    company_id = EXCLUDED.company_id,
                    default_account_id = EXCLUDED.default_account_id,
                    default_account_code = EXCLUDED.default_account_code,
                    odoo_write_date = EXCLUDED.odoo_write_date,
                    synced_at = NOW()
            """
            
            params = []
            synced = 0
            
            for r in generator:
                try:
                    company_id = self.get_internal_id('dim_companies', tenant_id, self.transformer.parse_odoo_many2one(r.get('company_id')))
                    currency_code = None
                    if r.get('currency_id'):
                        currency_code = r.get('currency_id')[1]
                        
                    default_account_id = None
                    default_account_code = None
                    acc_data = r.get('default_account_id')
                    if isinstance(acc_data, (list, tuple)) and acc_data:
                        default_account_id = acc_data[0]
                        if len(acc_data) > 1 and acc_data[1]:
                            parts = acc_data[1].split(' ', 1)
                            default_account_code = parts[0]
                        
                    params.append((
                        tenant_id, r['id'],
                        r.get('name'), r.get('code'), r.get('type'), currency_code, company_id,
                        default_account_id, default_account_code,
                        self.transformer.parse_odoo_datetime(r.get('write_date'))
                    ))
                    
                    if len(params) >= 1000:
                        self.execute_upsert_batch(query, params)
                        synced += len(params)
                        params.clear()
                except Exception as e:
                    logger.error(f"Error processing journal {r.get('id')}: {e}")
                    
            if params:
                self.execute_upsert_batch(query, params)
                synced += len(params)
                params.clear()
                
            elapsed = time.time() - start_time
            rate = synced / elapsed if elapsed > 0 else 0
            logger.info(f"[account.journal] Sync complete: {synced} records in {elapsed:.2f}s ({rate:.2f} rec/s)")
            
            return synced, 0
            
        except Exception as e:
            logger.error(f"Journal sync failed: {e}")
            raise e
