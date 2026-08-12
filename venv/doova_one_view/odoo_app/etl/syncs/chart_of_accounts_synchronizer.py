"""
Chart of Accounts synchronizer with auto-population of TenantFinancialMapping.
"""

import logging
import time
from typing import Tuple
from odoo_app.etl.syncs.base_synchronizer import BaseSynchronizer

logger = logging.getLogger(__name__)

# Keywords used to auto-detect accrued expense accounts
ACCRUED_KEYWORDS = ['accrued', 'accrual', 'provision', 'provisions']

# Keywords used to auto-detect short-term debt accounts
DEBT_KEYWORDS = ['loan', 'debt', 'credit line', 'borrowing', 'short-term loan', 'short term loan']


class ChartOfAccountsSynchronizer(BaseSynchronizer):
    """Synchronizes account.account (Chart of Accounts) and auto-populates TenantFinancialMapping."""

    def sync(self, tenant_id: str, last_sync_date: str = None, **kwargs) -> Tuple[int, int]:
        start_time = time.time()
        logger.info(f"Syncing Chart of Accounts for tenant {tenant_id}")

        domain = []
        if last_sync_date:
            domain.append(['write_date', '>', last_sync_date])

        try:
            model_fields = self.with_retry(self.odoo.get_fields, 'account.account').keys()
            requested_fields = [
                'id', 'code', 'name', 'account_type', 'reconcile', 'deprecated', 'company_id', 'write_date'
            ]
            available_fields = [f for f in requested_fields if f in model_fields]

            # Pre-fetch companies for fast lookup
            self.prefetch_ids('dim_companies', tenant_id)

            synced, failed = 0, 0
            params_list = []

            for account in self.fetch_paginated('account.account', domain, available_fields):
                try:
                    params_list.append((
                        tenant_id,
                        account['id'],
                        account.get('code', ''),
                        account.get('name', ''),
                        account.get('account_type'),
                        account.get('reconcile', False),
                        account.get('deprecated', False),
                        self.get_internal_id(
                            'dim_companies', tenant_id,
                            self.transformer.parse_odoo_many2one(account.get('company_id'))
                        ),
                        self.transformer.parse_odoo_datetime(account.get('write_date')),
                    ))
                    synced += 1
                except Exception as e:
                    logger.error(f"Error preparing account {account.get('id')}: {e}")
                    failed += 1

            # Batch upsert
            query = """
                INSERT INTO dim_chart_of_accounts (
                    tenant_id, odoo_id, code, name, account_type,
                    reconcile, deprecated, company_id, odoo_write_date, synced_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (tenant_id, odoo_id) DO UPDATE SET
                    code = EXCLUDED.code,
                    name = EXCLUDED.name,
                    account_type = EXCLUDED.account_type,
                    reconcile = EXCLUDED.reconcile,
                    deprecated = EXCLUDED.deprecated,
                    company_id = EXCLUDED.company_id,
                    odoo_write_date = EXCLUDED.odoo_write_date,
                    synced_at = NOW()
            """
            self.execute_upsert_batch(query, params_list)
            self.db.conn.commit()

            # Auto-populate financial mapping after sync
            self._auto_populate_financial_mapping(tenant_id)

            self.log_sync_performance('account.account', start_time, synced)
            return synced, failed

        except Exception as e:
            logger.error(f"Chart of Accounts sync failed: {e}")
            raise

    def _auto_populate_financial_mapping(self, tenant_id: str):
        """
        Auto-detect accrued expense and short-term debt account codes
        from the synced Chart of Accounts and populate TenantFinancialMapping.
        """
        logger.info(f"Auto-populating financial mapping for tenant {tenant_id}")

        # Fetch all liability_current accounts for this tenant
        query = """
            SELECT code, name FROM dim_chart_of_accounts
            WHERE tenant_id = %s
              AND account_type = 'liability_current'
              AND deprecated = false
        """
        rows = self.db.fetch_all(query, (tenant_id,))

        accrued_codes = []
        debt_codes = []

        for code, name in rows:
            name_lower = (name or '').lower()

            if any(kw in name_lower for kw in ACCRUED_KEYWORDS):
                accrued_codes.append(code)
            elif any(kw in name_lower for kw in DEBT_KEYWORDS):
                debt_codes.append(code)

        # Upsert into tenant_financial_mappings
        # We use a raw SQL upsert because we are inside the ETL pipeline (raw DB connection)
        upsert_query = """
            INSERT INTO tenant_financial_mappings (
                tenant_id, accrued_expense_prefixes, short_term_debt_prefixes,
                created_at, updated_at
            )
            VALUES (%s, %s::jsonb, %s::jsonb, NOW(), NOW())
            ON CONFLICT (tenant_id) DO UPDATE SET
                accrued_expense_prefixes = EXCLUDED.accrued_expense_prefixes,
                short_term_debt_prefixes = EXCLUDED.short_term_debt_prefixes,
                updated_at = NOW()
        """
        import json
        self.db.execute(upsert_query, (
            tenant_id,
            json.dumps(accrued_codes),
            json.dumps(debt_codes),
        ))
        self.db.conn.commit()

        logger.info(
            f"Financial mapping for tenant {tenant_id}: "
            f"accrued={accrued_codes}, debt={debt_codes}"
        )
