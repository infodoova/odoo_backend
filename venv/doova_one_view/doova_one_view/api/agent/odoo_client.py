"""
Odoo XML-RPC client for direct interaction with Odoo instances.
Used for real-time data lookups and verification.
"""

import os
import xmlrpc.client
from .config import AgentConfig

class OdooClient:
    def __init__(self):
        self.url = AgentConfig.ODOO_URL
        self.db = AgentConfig.ODOO_DB
        self.username = AgentConfig.ODOO_USERNAME
        self.api_key = AgentConfig.ODOO_API_KEY

        if not all([self.url, self.db, self.username, self.api_key]):
            raise RuntimeError(
                "Missing Odoo connection values. "
                "Check ODOO_URL, ODOO_DB, ODOO_USERNAME, ODOO_API_KEY in .env"
            )

        self.common = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/common")
        self.models = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/object")

        try:
            self.uid = self.common.authenticate(
                self.db,
                self.username,
                self.api_key,
                {}
            )
        except Exception as e:
            raise RuntimeError(f"Odoo connection failed: {str(e)}")

        if not self.uid:
            raise RuntimeError(
                "Odoo authentication failed. Check ODOO_DB, ODOO_USERNAME, and ODOO_API_KEY."
            )

    def version(self):
        return self.common.version()

    def search_read(
        self,
        model: str,
        domain: list,
        fields: list,
        limit: int = 100,
        offset: int = 0,
        order: str | None = None,
    ) -> list[dict]:
        kwargs = {
            "fields": fields,
            "limit": limit,
            "offset": offset,
        }

        if order:
            kwargs["order"] = order

        return self.models.execute_kw(
            self.db,
            self.uid,
            self.api_key,
            model,
            "search_read",
            [domain],
            kwargs,
        )

    def search_count(self, model: str, domain: list) -> int:
        return self.models.execute_kw(
            self.db,
            self.uid,
            self.api_key,
            model,
            "search_count",
            [domain],
        )

    def get_record(self, model: str, res_id: int, fields: list | None = None) -> dict | None:
        """Fetch a single record by ID."""
        records = self.search_read(model, [["id", "=", res_id]], fields or [], limit=1)
        return records[0] if records else None
