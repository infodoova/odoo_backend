"""
Accounting fact table synchronizer
"""

import logging
import time
from typing import Tuple, List, Dict
from odoo_app.etl.syncs.base_synchronizer import BaseSynchronizer

logger = logging.getLogger(__name__)


class AccountMoveSynchronizer(BaseSynchronizer):
    """Synchronizes account.move and account.move.line (accounting fact tables)"""
    
    def sync(self, tenant_id: str, last_sync_date: str = None, **kwargs) -> Tuple[int, int]:
        """
        High-performance batch sync for account moves and lines.
        """
        start_time = time.time()
        logger.info(f"Starting accounting batch sync for tenant {tenant_id}")
        
        # Pre-fetch dimensions for fast lookup
        self.prefetch_ids('dim_partners', tenant_id)
        self.prefetch_ids('dim_companies', tenant_id)
        self.prefetch_ids('dim_products', tenant_id)
        
        domain = []
        if last_sync_date:
            domain.append(['write_date', '>', last_sync_date])
        
        try:
            # 1. Prepare Metadata
            move_fields = self.with_retry(self.odoo.get_fields, 'account.move').keys()
            line_fields = self.with_retry(self.odoo.get_fields, 'account.move.line').keys()
            
            req_move_fields = [
                'id', 'name', 'partner_id', 'company_id', 'date', 'invoice_date',
                'invoice_date_due', 'move_type', 'state', 'payment_state',
                'amount_untaxed', 'amount_tax', 'amount_total', 'amount_residual',
                'currency_id', 'invoice_origin', 'ref', 'write_date'
            ]
            req_line_fields = [
                'id', 'move_id', 'product_id', 'partner_id', 'company_id',
                'account_id', 'account_type', 'debit', 'credit', 'balance', 'amount_currency',
                'currency_id', 'quantity', 'price_unit', 'price_subtotal',
                'name', 'write_date'
            ]
            
            move_fields_avail = [f for f in req_move_fields if f in move_fields]
            line_fields_avail = [f for f in req_line_fields if f in line_fields]
            
            synced, failed = 0, 0
            
            # 2. Process in Batches
            batch_size = 200
            move_generator = self.fetch_paginated(
                model='account.move',
                domain=domain,
                fields=move_fields_avail,
                batch_size=batch_size
            )
            
            current_batch = []
            for move in move_generator:
                current_batch.append(move)
                
                if len(current_batch) >= batch_size:
                    s, f = self._process_move_batch(tenant_id, current_batch, line_fields_avail)
                    synced += s
                    failed += f
                    current_batch = []
            
            # Final batch
            if current_batch:
                s, f = self._process_move_batch(tenant_id, current_batch, line_fields_avail)
                synced += s
                failed += f
            
            self.log_sync_performance('account.move', start_time, synced)
            return synced, failed
            
        except Exception as e:
            logger.error(f"Accounting sync failed: {e}")
            raise

    def _process_move_batch(self, tenant_id: str, moves: List[dict], line_fields: List[str]) -> Tuple[int, int]:
        """
        Process a batch of moves and their lines.
        """
        move_params = []
        move_odoo_ids = []
        
        for move in moves:
            try:
                partner_id = self.get_internal_id('dim_partners', tenant_id, self.transformer.parse_odoo_many2one(move.get('partner_id')))
                company_id = self.get_internal_id('dim_companies', tenant_id, self.transformer.parse_odoo_many2one(move.get('company_id')))
                
                # Handle currency - Odoo returns [id, name] for Many2one
                currency_data = move.get('currency_id')
                currency_code = currency_data[1] if isinstance(currency_data, (list, tuple)) else None

                move_params.append((
                    tenant_id, move['id'], move.get('name'), company_id, partner_id,
                    self.transformer.parse_odoo_date(move.get('date')),
                    self.transformer.get_date_id(move.get('date')),
                    self.transformer.parse_odoo_date(move.get('invoice_date')),
                    self.transformer.get_date_id(move.get('invoice_date')),
                    self.transformer.parse_odoo_date(move.get('invoice_date_due')),
                    move.get('move_type'), move.get('state'), move.get('payment_state'),
                    self.transformer.parse_odoo_decimal(move.get('amount_untaxed', 0)),
                    self.transformer.parse_odoo_decimal(move.get('amount_tax', 0)),
                    self.transformer.parse_odoo_decimal(move.get('amount_total', 0)),
                    self.transformer.parse_odoo_decimal(move.get('amount_residual', 0)),
                    currency_code, move.get('invoice_origin'), move.get('ref'),
                    self.transformer.parse_odoo_datetime(move.get('write_date'))
                ))
                move_odoo_ids.append(move['id'])
            except Exception as e:
                logger.error(f"Error preparing move {move.get('id')}: {e}")

        # 1. Batch Upsert Moves
        move_query = """
            INSERT INTO fact_account_moves (
                tenant_id, odoo_id, odoo_name, company_id, partner_id,
                date, date_id, invoice_date, invoice_date_id, invoice_date_due,
                move_type, state, payment_state, amount_untaxed, amount_tax,
                amount_total, amount_residual, currency_code, invoice_origin,
                ref, odoo_write_date, synced_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (tenant_id, odoo_id) DO UPDATE SET 
                state = EXCLUDED.state, payment_state = EXCLUDED.payment_state,
                amount_total = EXCLUDED.amount_total, amount_residual = EXCLUDED.amount_residual,
                odoo_write_date = EXCLUDED.odoo_write_date, synced_at = NOW()
        """
        self.execute_upsert_batch(move_query, move_params)
        move_params.clear()

        # 2. Bulk Fetch All Lines
        line_query = """
            INSERT INTO fact_account_move_lines (
                tenant_id, account_move_id, odoo_id, odoo_move_id,
                product_id, partner_id, company_id, account_code,
                account_name, account_type, debit, credit, balance,
                amount_currency, currency_code, quantity, price_unit,
                price_subtotal, name, odoo_write_date, synced_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (tenant_id, odoo_id) DO UPDATE SET 
                debit = EXCLUDED.debit, credit = EXCLUDED.credit,
                balance = EXCLUDED.balance, account_type = COALESCE(EXCLUDED.account_type, fact_account_move_lines.account_type),
                odoo_write_date = EXCLUDED.odoo_write_date,
                synced_at = NOW()
        """
        
        line_params = []
        line_generator = self.fetch_paginated(
            'account.move.line',
            domain=[['move_id', 'in', move_odoo_ids]],
            fields=line_fields
        )

        for line in line_generator:
            try:
                move_odoo_id = self.transformer.parse_odoo_many2one(line.get('move_id'))
                account_move_id = self.get_internal_id('fact_account_moves', tenant_id, move_odoo_id)
                
                product_id = self.get_internal_id('dim_products', tenant_id, self.transformer.parse_odoo_many2one(line.get('product_id')))
                partner_id = self.get_internal_id('dim_partners', tenant_id, self.transformer.parse_odoo_many2one(line.get('partner_id')))
                company_id = self.get_internal_id('dim_companies', tenant_id, self.transformer.parse_odoo_many2one(line.get('company_id')))
                
                # Extract account info if available
                account_data = line.get('account_id')
                account_code = None
                account_name = None
                account_odoo_id = None
                if isinstance(account_data, (list, tuple)):
                    account_odoo_id = account_data[0]
                    # Odoo often returns [id, "code name"]
                    parts = account_data[1].split(' ', 1)
                    account_code = parts[0]
                    account_name = parts[1] if len(parts) > 1 else parts[0]

                # account_type: prefer direct Odoo field, fallback to CoA lookup
                account_type = line.get('account_type') or None
                if not account_type and account_code:
                    account_type = self._lookup_account_type(tenant_id, account_code)

                currency_data = line.get('currency_id')
                currency_code = currency_data[1] if isinstance(currency_data, (list, tuple)) else None

                line_params.append((
                    tenant_id, account_move_id, line['id'], move_odoo_id,
                    product_id, partner_id, company_id, account_code,
                    account_name, account_type,
                    self.transformer.parse_odoo_decimal(line.get('debit', 0)),
                    self.transformer.parse_odoo_decimal(line.get('credit', 0)),
                    self.transformer.parse_odoo_decimal(line.get('balance', 0)),
                    self.transformer.parse_odoo_decimal(line.get('amount_currency', 0)),
                    currency_code,
                    self.transformer.parse_odoo_decimal(line.get('quantity', 0)),
                    self.transformer.parse_odoo_decimal(line.get('price_unit', 0)),
                    self.transformer.parse_odoo_decimal(line.get('price_subtotal', 0)),
                    line.get('name'),
                    self.transformer.parse_odoo_datetime(line.get('write_date'))
                ))

                if len(line_params) >= 1000:
                    self.execute_upsert_batch(line_query, line_params)
                    line_params.clear()

            except Exception as e:
                logger.error(f"Error preparing accounting line {line.get('id')}: {e}")

        if line_params:
            self.execute_upsert_batch(line_query, line_params)
            line_params.clear()
        
        return len(moves), 0

    def _lookup_account_type(self, tenant_id: str, account_code: str):
        """
        Look up account_type from the synced Chart of Accounts.
        Uses the internal ID cache for performance.
        """
        cache_key = f"coa_type:{tenant_id}:{account_code}"
        if cache_key in self._id_cache:
            return self._id_cache[cache_key]

        query = "SELECT account_type FROM dim_chart_of_accounts WHERE tenant_id = %s AND code = %s LIMIT 1"
        result = self.db.fetch_one(query, (tenant_id, account_code))
        account_type = result[0] if result else None
        self._id_cache[cache_key] = account_type
        return account_type

    def backfill_account_types(self, tenant_id: str) -> int:
        """
        Backfill account_type for existing move lines where it is NULL,
        using the synced dim_chart_of_accounts table.
        Call this after a Chart of Accounts sync to fix historical data.
        """
        query = """
            UPDATE fact_account_move_lines l
            SET account_type = c.account_type
            FROM dim_chart_of_accounts c
            WHERE l.tenant_id = c.tenant_id
              AND l.account_code = c.code
              AND l.tenant_id = %s
              AND l.account_type IS NULL
              AND c.account_type IS NOT NULL
        """
        self.db.execute(query, (tenant_id,))
        updated = self.db.cursor.rowcount
        self.db.conn.commit()
        logger.info(f"Backfilled account_type for {updated} move lines (tenant {tenant_id})")
        return updated
