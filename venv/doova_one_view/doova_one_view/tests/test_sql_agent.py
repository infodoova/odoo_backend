# doova_one_view/tests/test_sql_agent.py

import unittest
from doova_one_view.api.agent.sql_agent import is_safe_read_only_sql, extract_sql_from_text


class TestSQLAgentSafety(unittest.TestCase):

    # ── Safe SELECT queries ───────────────────────────────────────────────────

    def test_safe_select_queries(self):
        valid_queries = [
            "SELECT * FROM dim_companies WHERE tenant_id = '123'",
            "SELECT count(*), sum(amount_total) FROM fact_sales_orders GROUP BY tenant_id",
            "WITH monthly_sales AS (SELECT date_trunc('month', date_order) AS m, sum(amount_total) FROM fact_sales_orders GROUP BY 1) SELECT * FROM monthly_sales",
            "select id, name from dim_products limit 50",
            "SELECT p.name, SUM(s.qty) FROM dim_products p JOIN fact_sales_orders s ON p.id = s.product_id GROUP BY p.name ORDER BY 2 DESC",
        ]
        for q in valid_queries:
            self.assertTrue(is_safe_read_only_sql(q), f"Query should be safe: {q}")

    # ── Blocked mutating queries ──────────────────────────────────────────────

    def test_blocked_mutating_queries(self):
        unsafe_queries = [
            "INSERT INTO dim_companies (id, name) VALUES (1, 'Hacker')",
            "UPDATE fact_sales_orders SET amount_total = 0 WHERE id = 1",
            "DELETE FROM dim_products WHERE id = 5",
            "DROP TABLE dim_companies",
            "ALTER TABLE dim_products ADD COLUMN hacked text",
            "TRUNCATE fact_account_moves",
            "GRANT ALL ON dim_companies TO public",
            "SELECT * FROM dim_companies; DROP TABLE dim_companies;",
        ]
        for q in unsafe_queries:
            self.assertFalse(is_safe_read_only_sql(q), f"Query should be rejected as unsafe: {q}")

    # ── Case-insensitive blocking ─────────────────────────────────────────────

    def test_blocked_keywords_are_case_insensitive(self):
        """Mutating keywords must be blocked regardless of case."""
        case_variants = [
            "insert into dim_companies values (1, 'x')",
            "Delete FROM dim_products",
            "dRoP tAbLe dim_companies",
            "UPDATE fact_sales_orders set amount = 0",
            "truncate fact_account_moves",
        ]
        for q in case_variants:
            self.assertFalse(is_safe_read_only_sql(q), f"Case variant should be blocked: {q}")

    # ── SQL extraction from LLM text ──────────────────────────────────────────

    def test_extract_sql_from_markdown_block(self):
        llm_text = """
        Here is the query you requested:
        ```sql
        SELECT id, name FROM dim_companies WHERE tenant_id = 'test-id';
        ```
        This query retrieves companies.
        """
        extracted = extract_sql_from_text(llm_text)
        self.assertIsNotNone(extracted)
        self.assertTrue(extracted.lower().startswith("select"))

    def test_extract_sql_from_generic_block(self):
        llm_text = """
        ```
        SELECT sum(amount_total) FROM fact_sales_orders;
        ```
        """
        extracted = extract_sql_from_text(llm_text)
        self.assertIsNotNone(extracted)
        self.assertIn("fact_sales_orders", extracted)

    def test_extract_sql_no_code_block_returns_none_or_raw(self):
        """Text without any code block should return None or the raw text."""
        llm_text = "I cannot answer that question."
        extracted = extract_sql_from_text(llm_text)
        # Acceptable: None or a string; must not raise an exception
        self.assertTrue(extracted is None or isinstance(extracted, str))

    # ── Semicolon injection boundary ──────────────────────────────────────────

    def test_semicolon_injection_blocked(self):
        """Multiple statements separated by semicolons must be blocked."""
        injected = "SELECT * FROM dim_companies; DELETE FROM dim_companies;"
        self.assertFalse(is_safe_read_only_sql(injected),
                         "Semicolon-injected DELETE must be blocked")

    def test_second_statement_insert_blocked(self):
        injected = "SELECT id FROM dim_products; INSERT INTO dim_products (id) VALUES (99);"
        self.assertFalse(is_safe_read_only_sql(injected))

    # ── Tenant isolation is enforced at the caller level (not SQL safety) ─────

    def test_select_without_tenant_filter_is_syntactically_safe(self):
        """
        A SELECT without tenant_id is syntactically read-only — safety is enforced
        by the caller (tool layer), not the SQL safety check.
        """
        q = "SELECT * FROM dim_products"
        # This should pass the read-only safety check
        self.assertTrue(is_safe_read_only_sql(q))

    # ── Edge cases ────────────────────────────────────────────────────────────

    def test_empty_string_is_not_safe(self):
        self.assertFalse(is_safe_read_only_sql(""))

    def test_whitespace_only_is_not_safe(self):
        self.assertFalse(is_safe_read_only_sql("   "))

    def test_cte_with_safe_body_is_allowed(self):
        q = (
            "WITH revenue AS (SELECT tenant_id, SUM(amount_total) AS total "
            "FROM fact_sales_orders GROUP BY tenant_id) "
            "SELECT * FROM revenue WHERE tenant_id = 'abc'"
        )
        self.assertTrue(is_safe_read_only_sql(q))


if __name__ == "__main__":
    unittest.main()
