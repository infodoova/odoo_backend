"""
Phase 3 of AGENT_FIXES_PLAN.md: invoice and record tools, server-built tables,
the SQL fallback returning real rows, prompt content, and per-run token usage.

No database and no network: queries and the model are replaced with stubs.
"""

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from doova_one_view.api.agent import table_sink
from doova_one_view.api.agent.sql_agent import (
    _DESTRUCTIVE_REQUEST,
    rows_to_markdown,
    run_sql_agent,
)
from doova_one_view.api.agent.tools_refactored import records
from doova_one_view.api.agent.tools_refactored.records import (
    MAX_LIST_ROWS,
    get_invoice_summary_tool,
    list_records_tool,
)

TENANT = "f9ce5883-4a44-4046-9e7b-16ba73b97a50"
RUN_QUERY = "doova_one_view.api.agent.tools_refactored.records.run_query"


def _invoice_rows():
    return [
        {"move_type": "out_invoice", "currency_code": "XAF", "doc_count": 2923, "total": Decimal("3280427050.00"),
         "unpaid": Decimal("100.00"), "first_date": date(2022, 10, 18), "last_date": date(2026, 8, 24)},
        {"move_type": "out_refund", "currency_code": "XAF", "doc_count": 6, "total": Decimal("13913000.00"),
         "unpaid": Decimal("0"), "first_date": date(2023, 5, 17), "last_date": date(2026, 2, 16)},
    ]


def _record_row(ref, partner="Mane Ela", company="CONATUS", amount="9302000.00", status="posted", unpaid="9302000.00"):
    return {"reference": ref, "doc_date": date(2026, 8, 21), "partner": partner, "company": company,
            "amount": Decimal(amount), "currency": "XAF", "status": status, "unpaid": Decimal(unpaid)}


# ── table store ───────────────────────────────────────────────────────────────

class TableSinkTests(SimpleTestCase):
    def setUp(self):
        self.token = table_sink.start_table_sink()
        self.addCleanup(lambda: table_sink.end_table_sink(self.token))

    def test_marker_is_replaced_by_the_stored_table(self):
        marker = table_sink.register_table("| a |\n|---|\n| 1 |")
        self.assertEqual(marker, "{{TABLE:T1}}")
        out = table_sink.expand_table_markers(f"Here you go:\n{marker}\nDone.")
        self.assertIn("| a |\n|---|\n| 1 |", out)
        self.assertNotIn("{{TABLE", out)

    def test_table_the_model_forgot_to_place_is_appended(self):
        table_sink.register_table("| a |\n|---|\n| 1 |", always_show=True)
        out = table_sink.expand_table_markers("Latest invoices below.")
        self.assertTrue(out.endswith("| 1 |"))

    def test_optional_table_is_not_appended_when_unused(self):
        table_sink.register_table("| a |\n|---|\n| 1 |", always_show=False)
        self.assertEqual(table_sink.expand_table_markers("Just the total."), "Just the total.")

    def test_unknown_marker_is_removed(self):
        self.assertEqual(table_sink.expand_table_markers("Before {{TABLE:T9}} after"), "Before  after")

    def test_voice_replies_never_contain_tables(self):
        marker = table_sink.register_table("| a |\n|---|\n| 1 |", always_show=True)
        out = table_sink.expand_table_markers(f"Twenty invoices. {marker}", is_voice=True)
        self.assertNotIn("|", out)
        self.assertNotIn("{{", out)

    def test_two_tables_get_separate_markers(self):
        first = table_sink.register_table("| one |")
        second = table_sink.register_table("| two |")
        self.assertNotEqual(first, second)
        out = table_sink.expand_table_markers(f"{second} then {first}")
        self.assertLess(out.index("| two |"), out.index("| one |"))

    def test_without_a_run_nothing_is_stored(self):
        table_sink.end_table_sink(self.token)
        self.assertFalse(table_sink.sink_is_active())
        self.assertIsNone(table_sink.register_table("| a |"))
        self.token = table_sink.start_table_sink()  # so the cleanup can end it


# ── invoice summary ───────────────────────────────────────────────────────────

class InvoiceSummaryTests(SimpleTestCase):
    def test_no_tenant_is_refused(self):
        with patch(RUN_QUERY) as run_query:
            result = get_invoice_summary_tool(tenant_ids=None)
        self.assertEqual(result["status"], "ERROR")
        run_query.assert_not_called()

    def test_invoices_and_credit_notes_are_kept_separate_and_netted(self):
        with patch(RUN_QUERY, return_value=_invoice_rows()):
            result = get_invoice_summary_tool(tenant_ids=[TENANT], company_ids=[4])
        self.assertEqual(result["status"], "SUCCESS")
        self.assertEqual(result["invoice_count"], 2923)
        self.assertEqual(result["credit_note_count"], 6)
        self.assertEqual(result["currency"], "XAF")
        self.assertEqual(result["invoice_total"], 3280427050.0)
        self.assertEqual(result["credit_note_total"], 13913000.0)
        self.assertEqual(result["net_total"], 3266514050.0)
        self.assertEqual(result["average_invoice_value"], 1122280.89)
        self.assertEqual(result["first_document_date"], "2022-10-18")
        self.assertEqual(result["last_document_date"], "2026-08-24")
        self.assertIn("not the same as sales orders", result["message"])

    def test_query_reads_posted_customer_documents_for_the_tenant_and_company(self):
        with patch(RUN_QUERY, return_value=_invoice_rows()) as run_query:
            get_invoice_summary_tool(tenant_ids=[TENANT], company_ids=[4])
        sql, params = run_query.call_args.args
        self.assertIn("t.state = 'posted'", sql)
        self.assertIn("'out_invoice', 'out_refund'", sql)
        self.assertIn("t.tenant_id", sql)
        self.assertIn(TENANT, params.values())
        self.assertIn(4, params.values())

    def test_vendor_direction_reads_vendor_documents(self):
        with patch(RUN_QUERY, return_value=[]) as run_query:
            result = get_invoice_summary_tool(tenant_ids=[TENANT], direction="vendor")
        self.assertIn("'in_invoice', 'in_refund'", run_query.call_args.args[0])
        self.assertEqual(result["status"], "NO_DATA")

    def test_dates_are_passed_as_parameters(self):
        with patch(RUN_QUERY, return_value=_invoice_rows()) as run_query:
            get_invoice_summary_tool(tenant_ids=[TENANT], start_date="2026-01-01", end_date="2026-12-31")
        sql, params = run_query.call_args.args
        self.assertIn("BETWEEN", sql)
        self.assertEqual((params["rec_start"], params["rec_end"]), ("2026-01-01", "2026-12-31"))

    def test_several_currencies_are_not_added_together(self):
        rows = _invoice_rows() + [
            {"move_type": "out_invoice", "currency_code": "USD", "doc_count": 3, "total": Decimal("900.00"),
             "unpaid": Decimal("0"), "first_date": date(2026, 1, 1), "last_date": date(2026, 2, 1)},
        ]
        with patch(RUN_QUERY, return_value=rows):
            result = get_invoice_summary_tool(tenant_ids=[TENANT])
        self.assertNotIn("currency", result)
        self.assertEqual(set(result["totals_by_currency"]), {"XAF", "USD"})
        self.assertEqual(result["totals_by_currency"]["USD"]["net"], 900.0)

    def test_bad_direction_and_database_errors_are_reported_not_raised(self):
        self.assertEqual(get_invoice_summary_tool(tenant_ids=[TENANT], direction="sideways")["status"], "ERROR")
        with patch(RUN_QUERY, side_effect=RuntimeError("boom")):
            result = get_invoice_summary_tool(tenant_ids=[TENANT])
        self.assertEqual(result["status"], "ERROR")
        self.assertIn("boom", result["message"])


# ── record listing ────────────────────────────────────────────────────────────

class ListRecordsTests(SimpleTestCase):
    def _run(self, data, totals=None, sink=True, **kwargs):
        totals = totals if totals is not None else [{"currency": "XAF", "n": 2923, "total": Decimal("3280427050.00")}]
        token = table_sink.start_table_sink() if sink else None
        try:
            with patch(RUN_QUERY, side_effect=[data, totals]) as run_query:
                result = list_records_tool(tenant_ids=[TENANT], **kwargs)
            expanded = table_sink.expand_table_markers(result.get("table", "")) if sink else None
        finally:
            if token is not None:
                table_sink.end_table_sink(token)
        return result, run_query, expanded

    def test_no_tenant_is_refused(self):
        with patch(RUN_QUERY) as run_query:
            result = list_records_tool(tenant_ids=[])
        self.assertEqual(result["status"], "ERROR")
        run_query.assert_not_called()

    def test_table_has_the_exact_rows_and_true_totals(self):
        data = [_record_row("INV/2026/00499"), _record_row("INV/2026/00498", partner="MLEA", amount="669300.00", unpaid="0")]
        result, _, table = self._run(data)
        self.assertEqual(result["status"], "SUCCESS")
        self.assertEqual(result["total_count"], 2923)
        self.assertEqual(result["returned"], 2)
        self.assertTrue(result["has_more"])
        self.assertEqual(result["table"], "{{TABLE:T1}}")
        self.assertIn("| 1 | INV/2026/00499 | 2026-08-21 | Mane Ela | 9,302,000 | XAF | 9,302,000 | posted |", table)
        self.assertIn("| 2 | INV/2026/00498 | 2026-08-21 | MLEA | 669,300 | XAF | 0 | posted |", table)
        self.assertIn("Rows 1-2 of 2,923. Total of all 2,923: XAF 3,280,427,050.", table)
        self.assertIn("{{TABLE:T1}}", result["display_instruction"])
        self.assertIn("2,921 more exist", result["display_instruction"])
        self.assertNotIn("table_markdown", result)

    def test_without_a_run_the_table_is_returned_inline(self):
        result, _, _ = self._run([_record_row("INV/1")], totals=[{"currency": "XAF", "n": 1, "total": Decimal("9302000")}], sink=False)
        self.assertNotIn("table", result)
        self.assertIn("| INV/1 |", result["table_markdown"])
        self.assertIn("exactly as given", result["display_instruction"])

    def test_missing_values_are_blank_never_a_dash_placeholder(self):
        row = _record_row("INV/1", partner=None, company=None)
        result, _, table = self._run([row], totals=[{"currency": "XAF", "n": 1, "total": Decimal("9302000")}])
        self.assertNotIn("—", table)
        self.assertIn("| 1 | INV/1 | 2026-08-21 |  | 9,302,000 |", table)

    def test_pipes_in_names_cannot_break_the_table(self):
        row = _record_row("INV/1", partner="A | B")
        _, _, table = self._run([row], totals=[{"currency": "XAF", "n": 1, "total": Decimal("1")}])
        self.assertIn("A \\| B", table)

    def test_company_column_only_when_several_companies_are_listed(self):
        one = [_record_row("A", company="CONATUS"), _record_row("B", company="CONATUS")]
        many = [_record_row("A", company="CONATUS"), _record_row("B", company="Pittura")]
        _, _, table_one = self._run(one)
        _, _, table_many = self._run(many)
        self.assertNotIn("Company", table_one)
        self.assertIn("Company", table_many)

    def test_limit_is_capped_and_the_cap_is_explained(self):
        result, run_query, _ = self._run([_record_row("A")], limit="500")
        self.assertEqual(run_query.call_args_list[0].args[1]["rec_limit"], MAX_LIST_ROWS)
        self.assertTrue(any("capped" in n for n in result["notes"]))

    def test_offset_past_the_end_says_so(self):
        result, _, _ = self._run([], totals=[{"currency": "XAF", "n": 6, "total": Decimal("13913000")}], record_type="credit_notes", offset=99999)
        self.assertEqual(result["status"], "NO_DATA")
        self.assertIn("only 6", result["message"])

    def test_nothing_matching_says_no_records(self):
        result, _, _ = self._run([], totals=[], record_type="vendor_bills")
        self.assertEqual(result["status"], "NO_DATA")
        self.assertIn("No vendor bills match", result["message"])

    def test_unknown_record_type_status_and_sort_are_handled(self):
        with patch(RUN_QUERY) as run_query:
            self.assertEqual(list_records_tool(tenant_ids=[TENANT], record_type="payments")["status"], "ERROR")
            self.assertEqual(list_records_tool(tenant_ids=[TENANT], record_type="vendor_bills", status="bogus")["status"], "ERROR")
            run_query.assert_not_called()
        result, run_query, _ = self._run([_record_row("A")], sort="sideways")
        self.assertIn("ORDER BY COALESCE(t.invoice_date, t.date) DESC", run_query.call_args_list[0].args[0])
        self.assertTrue(any("Unknown sort" in n for n in result["notes"]))

    def test_query_is_scoped_filtered_and_sorted(self):
        _, run_query, _ = self._run(
            [_record_row("A")], record_type="customer_invoices", company_ids=[4], partner_name="mlea",
            start_date="2026-01-01", end_date="2026-06-30", sort="amount_desc", limit=5, offset=10,
        )
        sql, params = run_query.call_args_list[0].args
        self.assertIn("t.tenant_id", sql)
        self.assertIn("t.company_id", sql)
        self.assertIn("t.move_type IN ('out_invoice')", sql)
        self.assertIn("p.name ILIKE :rec_partner", sql)
        self.assertIn("ORDER BY t.amount_total DESC, t.id DESC", sql)
        self.assertEqual(params["rec_partner"], "%mlea%")
        self.assertEqual((params["rec_limit"], params["rec_offset"]), (5, 10))
        self.assertEqual(params["rec_state_0"], "posted")
        self.assertIn(TENANT, params.values())
        self.assertIn(4, params.values())
        totals_sql = run_query.call_args_list[1].args[0]
        self.assertIn("GROUP BY t.currency_code", totals_sql)
        self.assertNotIn("LIMIT", totals_sql)

    def test_sales_orders_default_to_confirmed_states_and_all_removes_the_filter(self):
        _, run_query, _ = self._run([_record_row("A")], record_type="sales_orders")
        params = run_query.call_args_list[0].args[1]
        self.assertEqual((params["rec_state_0"], params["rec_state_1"]), ("sale", "done"))
        _, run_query, _ = self._run([_record_row("A")], record_type="sales_orders", status="all")
        self.assertNotIn("t.state IN", run_query.call_args_list[0].args[0])

    def test_database_errors_are_reported_not_raised(self):
        with patch(RUN_QUERY, side_effect=RuntimeError("bad date")):
            result = list_records_tool(tenant_ids=[TENANT], start_date="nope")
        self.assertEqual(result["status"], "ERROR")


# ── SQL fallback ──────────────────────────────────────────────────────────────

class SqlFallbackTests(SimpleTestCase):
    def test_only_plain_requests_to_change_data_are_refused_up_front(self):
        for text in ("delete all invoices", "drop table fact_sales_orders", "UPDATE fact_sales_orders SET amount_total = 0",
                     "insert into dim_products values (1)", "alter table dim_companies add x int", "grant all to bob"):
            with self.subTest(text=text):
                self.assertTrue(_DESTRUCTIVE_REQUEST.search(text.lower()))
        for text in ("analyze sales by month", "show the latest update on our orders", "create a list of top customers",
                     "copy of invoice totals by company", "which products were replaced most often"):
            with self.subTest(text=text):
                self.assertFalse(_DESTRUCTIVE_REQUEST.search(text.lower()))

    def test_rows_are_rendered_exactly(self):
        rows = [{"name": "A | B", "total": Decimal("1500.50"), "n": 3, "note": None, "day": date(2026, 1, 2)},
                {"name": "C", "total": Decimal("20"), "n": 1000, "note": "x", "day": date(2026, 1, 3)}]
        text = rows_to_markdown(rows)
        self.assertIn("| name | total | n | note | day |", text)
        self.assertIn("| A \\| B | 1,500.5 | 3 |  | 2026-01-02 |", text)
        self.assertIn("| C | 20 | 1,000 | x | 2026-01-03 |", text)
        self.assertIn("Showing 2 of 2 rows", text)
        self.assertEqual(rows_to_markdown([]), "")

    def _run_agent(self, question, **kwargs):
        sql_reply = MagicMock(content=[MagicMock(text="```sql\nSELECT id, name FROM dim_companies WHERE tenant_id = 'x'\n```")])
        summary_reply = MagicMock(content=[MagicMock(text="There are two companies.")])
        client = MagicMock()
        client.messages.create.side_effect = [sql_reply, summary_reply]
        rows = [{"id": 1, "name": "A"}, {"id": 4, "name": "CONATUS"}]
        with patch("doova_one_view.api.agent.sql_agent.get_database_schema", return_value="Table: dim_companies"), \
             patch("doova_one_view.api.agent.sql_agent.anthropic.Anthropic", return_value=client), \
             patch("doova_one_view.api.agent.sql_agent.run_scoped_query", return_value=rows), \
             patch("doova_one_view.api.agent.utils.get_tenant_currency", return_value="XAF"), \
             patch("doova_one_view.api.kpi.service._get_rate_map", return_value={}), \
             patch("doova_one_view.api.agent.tools_refactored.common.get_per_tenant_exchange_rates", return_value={}):
            result = run_sql_agent(question, tenant_ids=[TENANT], **kwargs)
        return result, client

    def test_ordinary_question_with_a_blocked_looking_word_is_answered(self):
        result, _ = self._run_agent("analyze and create a list of our companies")
        self.assertTrue(result["success"])

    def test_real_rows_and_true_count_come_back(self):
        result, _ = self._run_agent("list our companies")
        self.assertEqual(result["row_count"], 2)
        self.assertEqual(result["rows"], [{"id": 1, "name": "A"}, {"id": 4, "name": "CONATUS"}])
        self.assertEqual(result["message"], "There are two companies.")

    def test_selected_company_reaches_the_sql_prompt(self):
        _, client = self._run_agent("list our invoices", company_ids=[4])
        prompt = client.messages.create.call_args_list[0].kwargs["messages"][0]["content"]
        self.assertIn("company id(s) 4", prompt)
        self.assertIn("company_id = 4", prompt)

    def test_destructive_request_is_refused_without_calling_the_model(self):
        client = MagicMock()
        with patch("doova_one_view.api.agent.sql_agent.anthropic.Anthropic", return_value=client):
            result = run_sql_agent("delete all invoices", tenant_ids=[TENANT])
        self.assertFalse(result["success"])
        client.messages.create.assert_not_called()


class SqlToolWrapperTests(SimpleTestCase):
    def _call(self, sql_result, sink=True):
        from doova_one_view.api.agent import langchain_tools

        token = table_sink.start_table_sink() if sink else None
        try:
            with patch.object(langchain_tools, "run_sql_agent", return_value=sql_result):
                reply = langchain_tools.ask_database_custom_question.invoke({"question": "q", "tenant_ids": [TENANT]})
            expanded = table_sink.expand_table_markers(reply["table"]) if isinstance(reply, dict) and "table" in reply else None
        finally:
            if token is not None:
                table_sink.end_table_sink(token)
        return reply, expanded

    def test_rows_count_and_table_marker_reach_the_model(self):
        rows = [{"id": 1}, {"id": 2}, {"id": 3}]
        reply, table = self._call({"success": True, "message": "Three rows.", "rows": rows, "row_count": 250})
        self.assertEqual(reply["row_count"], 250)
        self.assertEqual(reply["rows"], rows)
        self.assertEqual(reply["table"], "{{TABLE:T1}}")
        self.assertIn("| 3 |", table)

    def test_a_single_value_has_no_table(self):
        reply, _ = self._call({"success": True, "message": "One.", "rows": [{"n": 5}], "row_count": 1})
        self.assertNotIn("table", reply)

    def test_failures_still_return_the_message(self):
        reply, _ = self._call({"success": False, "message": "I can only run safe read-only SELECT queries."})
        self.assertEqual(reply, "I can only run safe read-only SELECT queries.")


# ── tool wrappers ─────────────────────────────────────────────────────────────

class RecordToolWrapperTests(SimpleTestCase):
    def test_record_tools_do_not_inherit_the_sessions_remembered_period(self):
        from doova_one_view.api.agent import langchain_tools

        remembered = {"start_date": "2026-01-01", "end_date": "2026-03-31", "label": "Q1 2026"}
        with patch("doova_one_view.api.agent.session_context.get_active_date_window", return_value=remembered), \
             patch.object(langchain_tools, "list_records_tool", return_value={"status": "SUCCESS"}) as listing, \
             patch.object(langchain_tools, "get_invoice_summary_tool", return_value={"status": "SUCCESS"}) as summary:
            langchain_tools.list_records.invoke({"record_type": "sales_orders", "tenant_ids": [TENANT]})
            langchain_tools.invoice_summary.invoke({"tenant_ids": [TENANT]})
        self.assertIsNone(listing.call_args.kwargs["start_date"])
        self.assertIsNone(listing.call_args.kwargs["end_date"])
        self.assertIsNone(summary.call_args.kwargs["start_date"])
        self.assertIsNone(summary.call_args.kwargs["end_date"])

    def test_an_explicit_period_is_used(self):
        from doova_one_view.api.agent import langchain_tools

        with patch.object(langchain_tools, "list_records_tool", return_value={"status": "SUCCESS"}) as listing:
            langchain_tools.list_records.invoke(
                {"record_type": "sales_orders", "tenant_ids": [TENANT], "start_date": "2026-03-01", "end_date": "2026-03-31"}
            )
        self.assertEqual(listing.call_args.kwargs["start_date"], "2026-03-01")
        self.assertEqual(listing.call_args.kwargs["end_date"], "2026-03-31")

    def test_new_tools_are_registered_and_sales_summary_says_it_counts_orders(self):
        from doova_one_view.api.agent.langchain_tools import agent_tools, sales_summary

        names = {t.name for t in agent_tools}
        self.assertLessEqual({"invoice_summary", "list_records"}, names)
        self.assertIn("SALES ORDERS, not invoices", sales_summary.description)


# ── prompt ────────────────────────────────────────────────────────────────────

class PromptContentTests(SimpleTestCase):
    def setUp(self):
        from doova_one_view.api.agent.prompts import STATIC_AGENT_INSTRUCTIONS

        self.text = STATIC_AGENT_INSTRUCTIONS

    def test_no_references_to_tools_that_do_not_exist(self):
        from doova_one_view.api.agent.langchain_tools import agent_tools

        names = {t.name for t in agent_tools}
        for stale in ("get_cash_flow_statement", "get_payment_reconciliation", "get_period_comparison_pnl",
                      "get_revenue_segmentation", "get_working_capital_efficiency"):
            self.assertNotIn(stale, self.text)
            self.assertIn(stale.removeprefix("get_"), names)

    def test_no_stale_tool_count(self):
        self.assertNotIn("43 specialized", self.text)

    def test_invoice_and_listing_rules_are_present(self):
        for needle in ("INVOICES VS ORDERS", "LISTS OF RECORDS", "ANSWER, DO NOT ASK", "invoice_summary", "list_records"):
            self.assertIn(needle, self.text)

    def test_tenant_profile_is_no_longer_forced_before_every_figure(self):
        self.assertNotIn("ALWAYS call `tenant_profile` FIRST", self.text)


# ── per-run usage and table substitution in the agent ─────────────────────────

class AgentRunTests(SimpleTestCase):
    def _agent(self, invoke):
        from doova_one_view.api.agent.langchain_agent import AgentCallbackHandler, DoovaLangChainAgent

        agent = object.__new__(DoovaLangChainAgent)
        agent.model_name = "claude-sonnet-5-5"
        agent.callback_handler = AgentCallbackHandler(model_name=agent.model_name)
        agent.last_token_usage = None
        agent.summarizer = MagicMock()
        agent.executor = MagicMock()
        agent.executor.invoke.side_effect = invoke
        return agent

    def _run(self, agent, **kwargs):
        with patch("doova_one_view.api.agent.utils.get_tenant_currency", return_value="XAF"), \
             patch("doova_one_view.api.agent.utils.replace_tenant_ids_with_names", side_effect=lambda text, *a, **k: text):
            return agent.run(message="hello", tenant_ids=[TENANT], chat_history=[], **kwargs)

    @staticmethod
    def _spend(input_tokens, output_tokens, answer="ok"):
        def invoke(_inputs, config=None):
            handler = config["callbacks"][0]
            handler.total_input_tokens += input_tokens
            handler.total_output_tokens += output_tokens
            handler.llm_call_count += 1
            handler.detected_models.add("claude-sonnet-5-5")
            return {"output": answer}
        return invoke

    def test_usage_out_holds_this_runs_usage_only(self):
        agent = self._agent(self._spend(100, 20))
        first = {}
        self._run(agent, usage_out=first)
        self.assertEqual((first["input_tokens"], first["output_tokens"], first["llm_calls"]), (100, 20, 1))

        agent.executor.invoke.side_effect = self._spend(5, 1)
        second = {}
        self._run(agent, usage_out=second)
        self.assertEqual((second["input_tokens"], second["output_tokens"]), (5, 1))
        self.assertEqual(first["input_tokens"], 100)  # the earlier run's figures are untouched

    def test_each_run_uses_its_own_counter_not_the_shared_one(self):
        seen = []

        def invoke(_inputs, config=None):
            seen.append(config["callbacks"][0])
            return {"output": "ok"}

        agent = self._agent(invoke)
        self._run(agent)
        self._run(agent)
        self.assertIsNot(seen[0], seen[1])
        self.assertIsNot(seen[0], agent.callback_handler)

    def test_table_marker_in_the_answer_is_replaced_with_the_exact_table(self):
        def invoke(_inputs, config=None):
            marker = table_sink.register_table("| ref |\n|---|\n| INV/1 |")
            return {"output": f"Latest invoice:\n{marker}\nThat is all."}

        text = self._run(self._agent(invoke))
        self.assertIn("| INV/1 |", text)
        self.assertNotIn("{{TABLE", text)
        self.assertFalse(table_sink.sink_is_active())

    def test_voice_answer_has_no_table(self):
        def invoke(_inputs, config=None):
            marker = table_sink.register_table("| ref |\n|---|\n| INV/1 |")
            return {"output": f"I found twenty invoices. {marker}"}

        text = self._run(self._agent(invoke), is_voice=True)
        self.assertNotIn("|", text)
        self.assertIn("twenty invoices", text)

    def test_the_store_is_closed_when_the_run_fails(self):
        def invoke(_inputs, config=None):
            table_sink.register_table("| a |")
            raise RuntimeError("model down")

        agent = self._agent(invoke)
        with self.assertRaises(RuntimeError):
            self._run(agent)
        self.assertFalse(table_sink.sink_is_active())
