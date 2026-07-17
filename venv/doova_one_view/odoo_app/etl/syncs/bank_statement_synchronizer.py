"""
Bank statement fact table synchronizer
"""

import logging
import time
from typing import Tuple, List, Dict
from odoo_app.etl.syncs.base_synchronizer import BaseSynchronizer

logger = logging.getLogger(__name__)


class BankStatementSynchronizer(BaseSynchronizer):
    """Synchronizes account.bank.statement and account.bank.statement.line"""

    def sync(self, tenant_id: str, last_sync_date: str = None, **kwargs) -> Tuple[int, int]:
        """
        High-performance batch sync for bank statements and their lines.
        """
        start_time = time.time()
        logger.info(f"Starting bank statement batch sync for tenant {tenant_id}")

        # Pre-fetch dimensions for fast lookup
        self.prefetch_ids('dim_partners', tenant_id)
        self.prefetch_ids('dim_companies', tenant_id)

        domain = []
        if last_sync_date:
            domain.append(['write_date', '>', last_sync_date])

        try:
            # 1. Prepare Metadata
            stmt_fields = self.with_retry(self.odoo.get_fields, 'account.bank.statement').keys()
            line_fields = self.with_retry(self.odoo.get_fields, 'account.bank.statement.line').keys()

            req_stmt_fields = [
                'id', 'name', 'date', 'company_id', 'journal_id',
                'balance_start', 'balance_end_real', 'state', 'write_date'
            ]
            req_line_fields = [
                'id', 'statement_id', 'date', 'name', 'amount',
                'partner_id', 'company_id', 'ref', 'write_date'
            ]

            stmt_fields_avail = [f for f in req_stmt_fields if f in stmt_fields]
            line_fields_avail = [f for f in req_line_fields if f in line_fields]

            synced, failed = 0, 0

            # 2. Process in Batches
            batch_size = 200
            stmt_generator = self.fetch_paginated(
                model='account.bank.statement',
                domain=domain,
                fields=stmt_fields_avail,
                batch_size=batch_size
            )

            current_batch = []
            for stmt in stmt_generator:
                current_batch.append(stmt)

                if len(current_batch) >= batch_size:
                    s, f = self._process_statement_batch(tenant_id, current_batch, line_fields_avail)
                    synced += s
                    failed += f
                    current_batch = []

            # Final batch
            if current_batch:
                s, f = self._process_statement_batch(tenant_id, current_batch, line_fields_avail)
                synced += s
                failed += f

            self.log_sync_performance('account.bank.statement', start_time, synced)
            return synced, failed

        except Exception as e:
            logger.error(f"Bank statement sync failed: {e}")
            raise

    def _process_statement_batch(self, tenant_id: str, statements: List[dict], line_fields: List[str]) -> Tuple[int, int]:
        """
        Process a batch of bank statements and their lines.
        """
        stmt_params = []
        stmt_odoo_ids = []

        for stmt in statements:
            try:
                company_id = self.get_internal_id('dim_companies', tenant_id, self.transformer.parse_odoo_many2one(stmt.get('company_id')))

                # Journal is a Many2one — store the display name
                journal_data = stmt.get('journal_id')
                journal_name = journal_data[1] if isinstance(journal_data, (list, tuple)) else None

                stmt_params.append((
                    tenant_id, stmt['id'], stmt.get('name'), company_id,
                    self.transformer.parse_odoo_date(stmt.get('date')),
                    self.transformer.get_date_id(stmt.get('date')),
                    journal_name,
                    self.transformer.parse_odoo_decimal(stmt.get('balance_start', 0)),
                    self.transformer.parse_odoo_decimal(stmt.get('balance_end_real', 0)),
                    stmt.get('state'),
                    self.transformer.parse_odoo_datetime(stmt.get('write_date'))
                ))
                stmt_odoo_ids.append(stmt['id'])
            except Exception as e:
                logger.error(f"Error preparing bank statement {stmt.get('id')}: {e}")

        # 1. Batch Upsert Statements
        stmt_query = """
            INSERT INTO fact_bank_statements (
                tenant_id, odoo_id, odoo_name, company_id,
                date, date_id, journal_name,
                balance_start, balance_end_real, state,
                odoo_write_date, synced_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (tenant_id, odoo_id) DO UPDATE SET
                balance_start = EXCLUDED.balance_start,
                balance_end_real = EXCLUDED.balance_end_real,
                state = EXCLUDED.state,
                odoo_write_date = EXCLUDED.odoo_write_date,
                synced_at = NOW()
        """
        self.execute_upsert_batch(stmt_query, stmt_params)
        stmt_params.clear()

        # 2. Bulk Fetch All Lines for this batch of statements
        line_query = """
            INSERT INTO fact_bank_statement_lines (
                tenant_id, statement_id, odoo_id,
                date, date_id, name, amount,
                partner_id, company_id, ref,
                odoo_write_date, synced_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (tenant_id, odoo_id) DO UPDATE SET
                amount = EXCLUDED.amount,
                name = EXCLUDED.name,
                partner_id = EXCLUDED.partner_id,
                ref = EXCLUDED.ref,
                odoo_write_date = EXCLUDED.odoo_write_date,
                synced_at = NOW()
        """

        line_params = []
        line_generator = self.fetch_paginated(
            'account.bank.statement.line',
            domain=[['statement_id', 'in', stmt_odoo_ids]],
            fields=line_fields
        )

        for line in line_generator:
            try:
                stmt_odoo_id = self.transformer.parse_odoo_many2one(line.get('statement_id'))
                statement_id = self.get_internal_id('fact_bank_statements', tenant_id, stmt_odoo_id)

                partner_id = self.get_internal_id('dim_partners', tenant_id, self.transformer.parse_odoo_many2one(line.get('partner_id')))
                company_id = self.get_internal_id('dim_companies', tenant_id, self.transformer.parse_odoo_many2one(line.get('company_id')))

                line_params.append((
                    tenant_id, statement_id, line['id'],
                    self.transformer.parse_odoo_date(line.get('date')),
                    self.transformer.get_date_id(line.get('date')),
                    line.get('name'),
                    self.transformer.parse_odoo_decimal(line.get('amount', 0)),
                    partner_id, company_id,
                    line.get('ref'),
                    self.transformer.parse_odoo_datetime(line.get('write_date'))
                ))

                if len(line_params) >= 1000:
                    self.execute_upsert_batch(line_query, line_params)
                    line_params.clear()

            except Exception as e:
                logger.error(f"Error preparing bank statement line {line.get('id')}: {e}")

        if line_params:
            self.execute_upsert_batch(line_query, line_params)
            line_params.clear()

        return len(statements), 0
