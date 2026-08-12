"""
Account Partial Reconcile synchronizer
"""

import logging
from typing import Tuple, List
from odoo_app.etl.syncs.base_synchronizer import BaseSynchronizer

logger = logging.getLogger(__name__)


class AccountPartialReconcileSynchronizer(BaseSynchronizer):
    """Synchronizes account.partial.reconcile to link payments to invoices"""

    def sync(self, tenant_id: str, last_sync_date: str = None, **kwargs) -> Tuple[int, int]:
        logger.info(f"Starting account.partial.reconcile sync for tenant {tenant_id}")

        domain = []
        # Not all Odoo versions reliable update write_date on reconciliations, 
        # but if it's there we use it for incremental sync
        if last_sync_date:
            domain.append(['max_date', '>=', last_sync_date[:10]]) # max_date is often just a Date, not Datetime

        try:
            model_fields = self.with_retry(self.odoo.get_fields, 'account.partial.reconcile').keys()
            requested_fields = ['id', 'debit_move_id', 'credit_move_id', 'amount', 'company_id', 'max_date']
            available_fields = [f for f in requested_fields if f in model_fields]

            # Pre-fetch companies and move lines for fast lookup
            self.prefetch_ids('dim_companies', tenant_id)

            synced, failed = 0, 0
            batch_size = 1000
            current_batch = []

            for rec in self.fetch_paginated('account.partial.reconcile', domain, available_fields, batch_size=batch_size):
                current_batch.append(rec)
                if len(current_batch) >= batch_size:
                    s, f = self._process_batch(tenant_id, current_batch)
                    synced += s
                    failed += f
                    current_batch = []

            if current_batch:
                s, f = self._process_batch(tenant_id, current_batch)
                synced += s
                failed += f

            logger.info(f"Synced {synced} partial reconciles, {failed} failed")
            return synced, failed

        except Exception as e:
            logger.error(f"Partial reconcile sync failed: {e}")
            raise

    def _process_batch(self, tenant_id: str, records: List[dict]) -> Tuple[int, int]:
        params = []
        synced, failed = 0, 0

        query = """
            INSERT INTO fact_account_partial_reconciles (
                tenant_id, odoo_id, debit_move_line_id, credit_move_line_id, amount, company_id, max_date, synced_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (tenant_id, odoo_id)
            DO UPDATE SET
                debit_move_line_id = EXCLUDED.debit_move_line_id,
                credit_move_line_id = EXCLUDED.credit_move_line_id,
                amount = EXCLUDED.amount,
                company_id = EXCLUDED.company_id,
                max_date = EXCLUDED.max_date,
                synced_at = NOW()
        """

        for rec in records:
            try:
                debit_odoo_id = self.transformer.parse_odoo_many2one(rec.get('debit_move_id'))
                credit_odoo_id = self.transformer.parse_odoo_many2one(rec.get('credit_move_id'))

                debit_internal_id = None
                if debit_odoo_id:
                    debit_internal_id = self.get_internal_id('fact_account_move_lines', tenant_id, debit_odoo_id)

                credit_internal_id = None
                if credit_odoo_id:
                    credit_internal_id = self.get_internal_id('fact_account_move_lines', tenant_id, credit_odoo_id)

                params.append((
                    tenant_id,
                    rec['id'],
                    debit_internal_id,
                    credit_internal_id,
                    self.transformer.parse_odoo_decimal(rec.get('amount', 0)),
                    self.get_internal_id(
                        'dim_companies', tenant_id,
                        self.transformer.parse_odoo_many2one(rec.get('company_id'))
                    ),
                    self.transformer.parse_odoo_date(rec.get('max_date'))
                ))
                synced += 1
            except Exception as e:
                self.log_sync_error('account.partial.reconcile', rec['id'], e)
                failed += 1

        if params:
            try:
                self.execute_upsert_batch(query, params)
            except Exception as e:
                logger.error(f"Batch upsert failed for account.partial.reconcile: {e}")
                # If batch fails, we don't know exactly which one failed in the execute_upsert_batch,
                # but we raise to fail the whole sync process safely
                raise

        return synced, failed
