"""
SQL agent guard: what the validator accepts, and what the database lets a query see.

* The validator tests need no database.
* The sandbox tests run against the configured warehouse (the same connection the SQL agent
  uses). They only read, and they skip themselves when it is unreachable or holds no tenant.
"""

import time
import unittest
import uuid

from sqlalchemy import text

from doova_one_view.api.agent.sql_agent import is_safe_read_only_sql
from doova_one_view.api.agent.sql_guard import UnsafeSQLError, check_sql, run_scoped_query


class ValidatorAcceptsNormalQueries(unittest.TestCase):
    QUERIES = [
        "SELECT * FROM dim_companies WHERE tenant_id = '123'",
        "SELECT count(*), sum(amount_total) FROM fact_sales_orders GROUP BY tenant_id",
        "WITH m AS (SELECT date_trunc('month', date_order) AS d, sum(amount_total) AS s "
        "FROM fact_sales_orders GROUP BY 1) SELECT * FROM m",
        "select id, name from dim_products limit 50",
        "SELECT p.name, SUM(l.price_subtotal) FROM fact_sales_order_lines l "
        "JOIN dim_products p ON l.product_id = p.id GROUP BY p.name ORDER BY 2 DESC LIMIT 10;",
        "SELECT to_char(date_order,'YYYY-MM') m, round(sum(amount_total)::numeric,2) "
        "FROM fact_sales_orders WHERE name ILIKE '%INV%' GROUP BY 1 -- monthly\nORDER BY 1",
        "SELECT COALESCE(sum(x),0)::numeric(12,2) FROM (SELECT 1 x) t",
        "WITH a AS (SELECT 1 x), b(y) AS (SELECT x FROM a) "
        "SELECT y, row_number() OVER (ORDER BY y) FROM b",
        "SELECT EXTRACT(year FROM date_order), count(*) FROM fact_sales_orders GROUP BY 1",
        "SELECT CASE WHEN amount_total > 0 THEN 'a' ELSE 'b' END FROM fact_sales_orders "
        "WHERE state IN ('sale','done')",
        "SELECT * FROM dim_products",  # tenant scope is applied by the database, not the text
    ]

    def test_normal_queries_pass(self):
        for q in self.QUERIES:
            reason, _ = check_sql(q)
            self.assertIsNone(reason, f"{reason}: {q}")

    def test_comments_are_removed_from_what_runs(self):
        _, executable = check_sql("SELECT 1 -- note\n")
        self.assertNotIn("note", executable)


class ValidatorRejectsDangerousQueries(unittest.TestCase):
    REJECTED = {
        "file read": "SELECT pg_read_file('/etc/passwd')",
        "sleep (DoS)": "SELECT pg_sleep(3600)",
        "select into": "SELECT * INTO leaked FROM dim_companies",
        "large object export": "SELECT lo_export(1, '/tmp/x')",
        "stacked statement": "SELECT 1; SET ROLE postgres",
        "DO block": "SELECT 1; DO $$ BEGIN PERFORM 1; END $$",
        "dollar quoting": "SELECT $a$x$a$",
        "schema-qualified": "SELECT * FROM public.app_users",
        "information_schema": "SELECT * FROM information_schema.tables",
        "catalog table": "SELECT * FROM pg_shadow",
        "catalog schema": "SELECT * FROM pg_catalog.pg_user",
        "settings": "SELECT current_setting('server_version')",
        "set_config": "SELECT set_config('x','y',false)",
        "reg cast": "SELECT 'app_users'::regclass",
        "query_to_xml": "SELECT query_to_xml('select 1', true, true, '')",
        "quoted function": 'SELECT "pg_sleep"(5)',
        "quoted schema": 'SELECT * FROM "public"."app_users"',
        "escape string": "SELECT E'\\x41'",
        "unlisted function": "SELECT version()",
        "dblink": "SELECT * FROM dblink('x','y') AS t(a int)",
        "row lock": "SELECT 1 FOR UPDATE",
        "table statement": "TABLE app_users",
        "insert": "INSERT INTO dim_companies VALUES (1)",
        "update in comment": "SELECT * FROM dim_companies; -- DROP TABLE dim_companies;",
        "update after block comment": "/* c */ UPDATE fact_sales_orders SET amount_total = 0;",
        "empty": "",
        "blank": "   ",
        "unterminated quote": "SELECT 'abc",
    }

    def test_each_is_rejected(self):
        for label, q in self.REJECTED.items():
            reason, _ = check_sql(q)
            self.assertIsNotNone(reason, f"{label} was accepted: {q}")

    def test_the_agent_screen_uses_the_same_rules(self):
        for label, q in self.REJECTED.items():
            self.assertFalse(is_safe_read_only_sql(q), label)


def _warehouse():
    """(engine, a tenant id that has sales orders) or None when not available."""
    try:
        from doova_one_view.api.agent.db import engine
        with engine.connect() as conn:
            row = conn.execute(text(
                "SELECT tenant_id::text FROM fact_sales_orders GROUP BY 1 ORDER BY count(*) DESC LIMIT 1"
            )).first()
        return (engine, row[0]) if row else None
    except Exception:
        return None


_WAREHOUSE = _warehouse()


@unittest.skipUnless(_WAREHOUSE, "warehouse not reachable or empty")
class ScopedRunnerEnforcesIsolationInTheDatabase(unittest.TestCase):
    def setUp(self):
        self.engine, self.tenant = _WAREHOUSE
        self.other = str(uuid.uuid4())

    def _count_direct(self):
        with self.engine.connect() as conn:
            return conn.execute(
                text("SELECT count(*) FROM fact_sales_orders WHERE tenant_id = :t"), {"t": self.tenant}
            ).scalar()

    def test_own_tenant_rows_are_visible(self):
        rows = run_scoped_query("SELECT count(*) AS n FROM fact_sales_orders", [self.tenant])
        self.assertEqual(rows[0]["n"], self._count_direct())

    def test_another_tenant_sees_nothing_of_it(self):
        rows = run_scoped_query("SELECT count(*) AS n FROM fact_sales_orders", [self.other])
        self.assertEqual(rows[0]["n"], 0)

    def test_where_clause_cannot_widen_the_scope(self):
        # the model ignores the tenant rule and asks for everything that is not this tenant
        rows = run_scoped_query(
            f"SELECT count(*) AS n FROM fact_sales_orders WHERE tenant_id <> '{self.tenant}'", [self.tenant]
        )
        self.assertEqual(rows[0]["n"], 0)

    def test_no_tenant_scope_is_refused(self):
        with self.assertRaises(UnsafeSQLError):
            run_scoped_query("SELECT 1", [])
        with self.assertRaises(UnsafeSQLError):
            run_scoped_query("SELECT 1", ["not-a-uuid"])

    def test_application_tables_do_not_exist_for_the_query(self):
        for table in ("app_users", "tenants", "password_reset_otps", "auth_user", "agent_chat_sessions"):
            with self.assertRaises(Exception) as ctx:
                run_scoped_query(f"SELECT * FROM {table}", [self.tenant])
            self.assertIn("does not exist", str(ctx.exception), table)

    def test_result_is_capped_and_streamed(self):
        rows = run_scoped_query("SELECT g FROM generate_series(1, 10000000) g", [self.tenant], max_rows=50)
        self.assertEqual(len(rows), 50)

    def test_statement_timeout_stops_a_runaway_query(self):
        started = time.time()
        with self.assertRaises(Exception) as ctx:
            run_scoped_query("SELECT count(*) FROM generate_series(1, 2000000000)", [self.tenant], timeout_ms=400)
        self.assertIn("timeout", str(ctx.exception).lower())
        self.assertLess(time.time() - started, 10)

    def test_connection_is_clean_afterwards(self):
        run_scoped_query("SELECT 1 AS x FROM dim_companies LIMIT 1", [self.tenant])
        with self.engine.connect() as conn:
            self.assertNotEqual(conn.execute(text("SHOW search_path")).scalar(), "pg_temp")
            self.assertEqual(
                conn.execute(text("SELECT count(*) FROM pg_class WHERE relpersistence = 't'")).scalar(), 0
            )
            # the unrestricted warehouse is visible again outside the sandbox
            self.assertEqual(conn.execute(text("SELECT count(*) FROM tenants")).scalar() >= 1, True)

    def test_company_filter_narrows_further(self):
        with self.engine.connect() as conn:
            company = conn.execute(text("SELECT id FROM dim_companies WHERE tenant_id = :t LIMIT 1"),
                                   {"t": self.tenant}).scalar()
        rows = run_scoped_query("SELECT count(*) AS n FROM dim_companies", [self.tenant], [company])
        self.assertEqual(rows[0]["n"], 1)


class SqlAgentUsesTheGuard(unittest.TestCase):
    """run_sql_agent must send the model's SQL through the scoped runner, never straight to the database."""

    TENANT = "11111111-1111-4111-8111-111111111111"

    def _run(self, **kwargs):
        from unittest.mock import MagicMock, patch
        from doova_one_view.api.agent.sql_agent import run_sql_agent

        sql_reply = MagicMock(content=[MagicMock(type="text", text="```sql\nSELECT id FROM dim_companies\n```")])
        summary = MagicMock(content=[MagicMock(type="text", text="ok")])
        client = MagicMock()
        client.messages.create.side_effect = [sql_reply, summary]
        with patch("doova_one_view.api.agent.sql_agent.get_database_schema", return_value="Table: dim_companies"), \
             patch("doova_one_view.api.agent.sql_agent.anthropic.Anthropic", return_value=client), \
             patch("doova_one_view.api.agent.sql_agent.run_scoped_query", return_value=[{"id": 1}]) as runner, \
             patch("doova_one_view.api.agent.sql_agent.run_query") as plain, \
             patch("doova_one_view.api.agent.utils.get_tenant_currency", return_value="XAF"), \
             patch("doova_one_view.api.kpi.service._get_rate_map", return_value={}), \
             patch("doova_one_view.api.agent.tools_refactored.common.get_per_tenant_exchange_rates", return_value={}):
            result = run_sql_agent("list companies", **kwargs)
        return result, client, runner, plain

    def test_query_runs_through_the_scoped_runner_with_tenant_and_company(self):
        result, _, runner, plain = self._run(tenant_ids=[self.TENANT], company_ids=[4])
        self.assertTrue(result["success"])
        runner.assert_called_once()
        args = runner.call_args.args
        self.assertEqual(args[1], [self.TENANT])
        self.assertEqual(args[2], [4])
        plain.assert_not_called()

    def test_without_a_tenant_nothing_is_asked_or_run(self):
        result, client, runner, plain = self._run(tenant_ids=None)
        self.assertFalse(result["success"])
        client.messages.create.assert_not_called()
        runner.assert_not_called()
        plain.assert_not_called()

    def test_application_tables_are_not_shown_to_the_model(self):
        from unittest.mock import patch
        from doova_one_view.api.agent import sql_agent

        rows = [
            {"table_name": "fact_sales_orders", "column_name": "id", "data_type": "integer"},
            {"table_name": "app_users", "column_name": "password_hash", "data_type": "text"},
            {"table_name": "tenants", "column_name": "api_key_encrypted", "data_type": "bytea"},
            {"table_name": "dim_products", "column_name": "name", "data_type": "text"},
        ]
        with patch.object(sql_agent, "run_query", return_value=rows):
            schema = sql_agent.get_database_schema.__wrapped__() if hasattr(
                sql_agent.get_database_schema, "__wrapped__") else sql_agent.get_database_schema()
        self.assertIn("fact_sales_orders", schema)
        self.assertIn("dim_products", schema)
        self.assertNotIn("app_users", schema)
        self.assertNotIn("password_hash", schema)
        self.assertNotIn("api_key_encrypted", schema)


if __name__ == "__main__":
    unittest.main()
