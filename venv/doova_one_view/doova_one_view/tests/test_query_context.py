# doova_one_view/tests/test_query_context.py

import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "doova_one_view.settings")
django.setup()

import unittest
from unittest.mock import patch, MagicMock
from doova_one_view.api.agent.query_context import (
    resolve_tenant_id,
    normalize_company_ids,
    normalize_tenant_ids,
    build_company_filter_sql,
    build_tenant_filter_sql,
)

class TestQueryContext(unittest.TestCase):

    def test_resolve_tenant_id_valid_uuid(self):
        valid_uuid = "3fa85f64-5717-4562-b3fc-2c963f66afa6"
        resolved = resolve_tenant_id(valid_uuid)
        self.assertEqual(resolved, valid_uuid)

    def test_resolve_tenant_id_empty_and_all(self):
        self.assertIsNone(resolve_tenant_id("all"))
        self.assertIsNone(resolve_tenant_id("all_tenants"))
        self.assertIsNone(resolve_tenant_id(""))
        self.assertIsNone(resolve_tenant_id(None))

    @patch("odoo_app.models.tenant.Tenant")
    def test_resolve_tenant_id_default_fallback(self, mock_tenant_model):
        mock_tenant_inst = MagicMock()
        mock_tenant_inst.id = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
        mock_tenant_model.objects.first.return_value = mock_tenant_inst

        resolved = resolve_tenant_id("default")
        self.assertEqual(resolved, "a1b2c3d4-e5f6-7890-abcd-ef1234567890")

    def test_normalize_company_ids(self):
        self.assertEqual(normalize_company_ids(company_id=26), [26])
        self.assertEqual(normalize_company_ids(company_id="26"), [26])
        self.assertEqual(normalize_company_ids(companies=[26, 27]), [26, 27])
        self.assertEqual(normalize_company_ids(company_id=None, companies=None), [])

    def test_build_company_filter_sql(self):
        sql, params = build_company_filter_sql("tenant-123", [26, 27], column_name="company_id")
        self.assertTrue("company_id" in sql)
        self.assertIn("comp_0", params)
        self.assertIn("comp_1", params)
        self.assertEqual(params["comp_0"], 26)
        self.assertEqual(params["comp_1"], 27)

    def test_build_tenant_filter_sql_empty(self):
        sql, params = build_tenant_filter_sql(tenant_id="all")
        self.assertEqual(sql, "")
        self.assertEqual(params, {})

if __name__ == "__main__":
    unittest.main()
