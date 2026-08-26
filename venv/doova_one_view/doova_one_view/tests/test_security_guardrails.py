# doova_one_view/tests/test_security_guardrails.py

import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "doova_one_view.settings")
django.setup()

import unittest
from unittest.mock import patch
from doova_one_view.api.agent.sql_agent import is_safe_read_only_sql
from doova_one_view.api.agent.query_context import build_tenant_filter_sql, build_company_filter_sql

class TestSecurityGuardrails(unittest.TestCase):

    def test_sql_mutation_rejection(self):
        """Verify that any destructive or mutating SQL is strictly blocked."""
        dangerous_queries = [
            "DROP TABLE fact_sales_orders;",
            "DELETE FROM dim_partners WHERE id = 1;",
            "UPDATE fact_sales_orders SET amount_total = 0;",
            "INSERT INTO odoo_app_tenant (id, name) VALUES ('hack', 'hack');",
            "TRUNCATE TABLE fact_account_moves;",
            "GRANT ALL PRIVILEGES ON DATABASE postgres TO public;",
            "ALTER TABLE dim_products DROP COLUMN price;",
            "EXEC pg_sleep(10);",
        ]
        for q in dangerous_queries:
            self.assertFalse(
                is_safe_read_only_sql(q),
                f"Security Failure: Dangerous SQL was erroneously permitted: {q}"
            )

    def test_sql_read_only_permission(self):
        """Verify legitimate read-only queries are permitted."""
        valid_queries = [
            "SELECT COUNT(*) FROM fact_sales_orders WHERE state = 'sale';",
            "WITH monthly_sales AS (SELECT date_trunc('month', date_order) AS m, SUM(amount_total) AS rev FROM fact_sales_orders GROUP BY 1) SELECT * FROM monthly_sales;",
            "SELECT p.name, SUM(l.price_subtotal) FROM fact_sales_order_lines l JOIN dim_products p ON l.product_id = p.id GROUP BY p.name ORDER BY 2 DESC LIMIT 10;"
        ]
        for q in valid_queries:
            self.assertTrue(
                is_safe_read_only_sql(q),
                f"False Positive: Safe query was blocked: {q}"
            )

    def test_tenant_isolation_filter_building(self):
        """Ensure tenant_id and tenant_ids filters enforce strict separation via parameter binding."""
        sql, params = build_tenant_filter_sql(
            tenant_id="3fa85f64-5717-4562-b3fc-2c963f66afa6",
            tenant_ids=["3fa85f64-5717-4562-b3fc-2c963f66afa6"],
            column_name="t.tenant_id",
            prefix="t_sec"
        )
        self.assertIn("t.tenant_id IN", sql)
        self.assertIn("t_sec_tenant_id_0", params)
        self.assertEqual(params["t_sec_tenant_id_0"], "3fa85f64-5717-4562-b3fc-2c963f66afa6")

if __name__ == "__main__":
    unittest.main()
