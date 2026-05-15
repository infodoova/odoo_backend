"""
User dimension synchronizer
"""

import logging
from typing import Tuple
from odoo_app.etl.syncs.base_synchronizer import BaseSynchronizer

logger = logging.getLogger(__name__)


class UserSynchronizer(BaseSynchronizer):
    """Synchronizes res.users"""

    def sync(self, tenant_id: str, last_sync_date: str = None, **kwargs) -> Tuple[int, int]:
        logger.info("Syncing users...")

        domain = [['active', 'in', [True, False]]]
        if last_sync_date:
            domain.append(['write_date', '>', last_sync_date])

        try:
            # Dynamically check for available fields (retriable)
            model_fields = self.with_retry(self.odoo.get_fields, 'res.users').keys()
            requested_fields = ['id', 'name', 'email', 'active', 'write_date']
            available_fields = [f for f in requested_fields if f in model_fields]

            synced, failed = 0, 0

            # Use paginated fetcher
            for user in self.fetch_paginated('res.users', domain, available_fields):
                try:
                    query = """
                        INSERT INTO dim_users (
                            tenant_id, odoo_id, name, email, is_active
                        )
                        VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT (tenant_id, odoo_id)
                        DO UPDATE SET
                            name = EXCLUDED.name,
                            email = EXCLUDED.email,
                            is_active = EXCLUDED.is_active
                    """

                    self.db.execute(query, (
                        tenant_id,
                        user['id'],
                        user['name'],
                        user.get('email'),
                        self.transformer.parse_odoo_boolean(user.get('active', True))
                    ))

                    synced += 1

                except Exception as e:
                    self.log_sync_error('res.users', user['id'], e)
                    failed += 1

            self.db.conn.commit()
            logger.info(f"Synced {synced} users, {failed} failed")
            return synced, failed

        except Exception as e:
            logger.error(f"User sync failed: {e}")
            raise
