"""
Answer quality fixes found while testing the chat:

1. Competitors: the assistant called a food importer (EGTC) a competitor of an appliance and car
   business, because a fixed sentence naming "CFAO, EGTC Group" as competitors was returned for
   every tenant. Competitors are now judged against the tenant's own product categories.
2. Layout: answers turned everything into bullets, nested lists under colon-ended bullets and
   repeated tables as lists; the SQL tool wrote a finished reply that the main model wrapped again.
3. Currency: dollar figures from web search were relabelled as XAF without conversion
   ("$1.02B" -> "XAF 1.02B", "US$750M" -> "USXAF 750M").
"""

import inspect
import unittest
from pathlib import Path

from django.test import SimpleTestCase

from doova_one_view.api.agent import prompts
from doova_one_view.api.agent.sql_agent import rows_for_display, rows_to_markdown
from doova_one_view.api.agent.utils import fix_currency_symbols

AGENT_DIR = Path(prompts.__file__).resolve().parent
HARDCODED_NAMES = ("EGTC", "CFAO", "Tienda Ideal", "Martinez Hermanos")


def _warehouse_tenant():
    try:
        from sqlalchemy import text
        from doova_one_view.api.agent.db import engine
        with engine.connect() as conn:
            row = conn.execute(text(
                "SELECT tenant_id::text FROM fact_sales_orders GROUP BY 1 ORDER BY count(*) DESC LIMIT 1"
            )).first()
        return row[0] if row else None
    except Exception:
        return None


_TENANT = _warehouse_tenant()


# ── 3. currency ──────────────────────────────────────────────────────────────

class CurrencySymbolTests(SimpleTestCase):
    def test_external_dollar_figures_are_not_relabelled(self):
        for text in (
            "a US$750M contract for a 500 MWp solar plant",
            "Imports were USD 1.02 billion, about $1.02B.",
            "The market is worth $200M (US dollars).",
            "Prices start at C$10 and HK$5.",
        ):
            self.assertEqual(fix_currency_symbols(text, "XAF"), text, text)

    def test_us_dollar_prefix_is_never_split(self):
        self.assertNotIn("USXAF", fix_currency_symbols("about US$200M in 2025", "XAF"))

    def test_bare_dollar_on_company_amounts_still_gets_the_tenant_code(self):
        self.assertEqual(fix_currency_symbols("Total revenue was $10000.", "XAF"), "Total revenue was XAF 10000.")
        self.assertEqual(fix_currency_symbols("Margin was 500$ this month", "XAF"), "Margin was 500 XAF this month")

    def test_usd_tenant_is_untouched(self):
        self.assertEqual(fix_currency_symbols("Revenue $100", "USD"), "Revenue $100")

    def test_web_search_answers_are_not_rewritten(self):
        from doova_one_view.api.agent import web_search_agent
        source = inspect.getsource(web_search_agent)
        self.assertNotIn("fix_currency_symbols(final_text", source)

    def test_prompt_keeps_the_source_currency_for_external_figures(self):
        template = prompts.AGENT_SYSTEM_PROMPT.messages[1].prompt.template
        self.assertNotIn("DO NOT output $ or USD under any circumstances", template)
        self.assertIn("EXTERNAL FIGURES", template)
        self.assertIn("MONEY FROM EXTERNAL SOURCES", prompts.WEB_SEARCH_SYSTEM_PROMPT_ADDITION)


# ── 1. competitors ───────────────────────────────────────────────────────────

class CompetitorRuleTests(SimpleTestCase):
    def test_no_customer_specific_company_names_in_prompts_or_profile(self):
        for path in (AGENT_DIR / "prompts.py", AGENT_DIR / "tools_refactored" / "common.py"):
            text = path.read_text(encoding="utf-8")
            for name in HARDCODED_NAMES:
                self.assertNotIn(name, text, f"{name} hardcoded in {path.name}")

    def test_competitor_is_defined_by_products_not_by_supply_chain_level(self):
        rules = prompts.STATIC_AGENT_INSTRUCTIONS
        self.assertIn("COMPETITOR RULES", rules)
        self.assertIn("SAME KINDS OF PRODUCTS", rules)
        self.assertIn("sells_categories", rules)
        self.assertIn("NOT a competitor", rules)
        web = prompts.WEB_SEARCH_SYSTEM_PROMPT_ADDITION
        self.assertNotIn("supply_chain_position", web)
        self.assertIn("same kinds of products", web)

    def test_trading_partners_are_checked_with_the_relationship_tool(self):
        from doova_one_view.api.agent.langchain_tools import agent_tools

        self.assertIn("company_relationship", {t.name for t in agent_tools})
        self.assertIn("company_relationship", prompts.STATIC_AGENT_INSTRUCTIONS)
        self.assertIn("company_relationship", prompts.WEB_SEARCH_SYSTEM_PROMPT_ADDITION)

    def test_a_relationship_is_context_not_a_verdict(self):
        rules = prompts.STATIC_AGENT_INSTRUCTIONS
        self.assertIn("A trading relationship is context, not a verdict", rules)
        self.assertIn("can still compete", rules)
        self.assertNotIn("If it does, it is a customer or supplier: say so, and do not call it a competitor", rules)


class RelationshipSearchTermTests(SimpleTestCase):
    def test_generic_words_and_legal_forms_are_dropped(self):
        from doova_one_view.api.agent.tools_refactored.relationships import search_terms

        self.assertEqual(search_terms("CFAO Motors Guinea Ecuatorial"), ["cfao"])
        self.assertEqual(search_terms("EGTC Group"), ["egtc"])
        self.assertEqual(search_terms("Nexis Group Sal - Offshore"), ["nexis"])
        self.assertEqual(search_terms("Steel Proyect S.L."), ["proyect", "steel"])
        self.assertEqual(search_terms("Seguibat S.A"), ["seguibat"])

    def test_an_acronym_comes_first_and_nationality_words_are_dropped(self):
        from doova_one_view.api.agent.tools_refactored.relationships import acronyms, search_terms

        self.assertEqual(search_terms("EGTC Equato Guinean Trading Company"), ["egtc"])
        self.assertEqual(acronyms("CFAO Motors"), ["cfao"])
        self.assertEqual(acronyms("Nexis Group SAL - Offshore"), [])  # SAL is a legal form
        self.assertEqual(search_terms("TCL Electronics Holdings"), ["tcl"])

    def test_an_all_generic_name_still_searches_something(self):
        from doova_one_view.api.agent.tools_refactored.relationships import search_terms

        self.assertEqual(search_terms("International Trading Group"), ["international"])

    def test_nothing_usable(self):
        from doova_one_view.api.agent.tools_refactored.relationships import get_company_relationship_tool, search_terms

        self.assertEqual(search_terms("S.A."), [])
        res = get_company_relationship_tool("S.A.", tenant_ids=["11111111-1111-4111-8111-111111111111"])
        self.assertEqual(res["status"], "ERROR")

    def test_word_start_matching(self):
        from doova_one_view.api.agent.tools_refactored.relationships import _starts_a_word

        self.assertTrue(_starts_a_word("egtc", "EGTC BATA"))
        self.assertTrue(_starts_a_word("egtc", "hussein jaber-egtc"))
        self.assertFalse(_starts_a_word("egtc", "MEGTCX"))
        self.assertTrue(_starts_a_word("cfao", "cfao MOBILTY"))


@unittest.skipUnless(_TENANT, "warehouse not reachable or empty")
class RelationshipToolOnRealDataTests(SimpleTestCase):
    """Reads the configured warehouse (no writes)."""

    def _rel(self, name):
        from doova_one_view.api.agent.tools_refactored.relationships import get_company_relationship_tool
        return get_company_relationship_tool(name, tenant_ids=[_TENANT])

    def test_the_full_public_name_finds_the_short_record_name(self):
        res = self._rel("CFAO Motors Guinea Ecuatorial")
        if not res["matches"]:
            self.skipTest("no CFAO record in this database")
        self.assertIn("cfao", res["matches"][0]["name"].lower())
        self.assertIn(res["relationship"], ("supplier", "customer", "customer and supplier",
                                            "contact only (no orders, invoices or bills)"))

    def test_an_acronym_match_counts_as_the_same_company(self):
        res = self._rel("EGTC Equato Guinean Trading Company")
        if not res["matches"]:
            self.skipTest("no EGTC record in this database")
        self.assertFalse(res["relationship"].startswith("possible"), res["relationship"])
        self.assertTrue(all(m["match"] == "full name" for m in res["matches"] if "egtc" in m["name"].lower()))

    def test_result_shape(self):
        res = self._rel("Samsung Electronics Worldwide Holdings")
        self.assertEqual(res["status"], "SUCCESS")
        for key in ("searched_for", "search_terms", "relationship", "summary", "matches", "total_matches", "currency"):
            self.assertIn(key, res)

    def test_largest_trading_partner_is_reported_with_its_activity(self):
        from sqlalchemy import text
        from doova_one_view.api.agent.db import engine

        with engine.connect() as conn:
            row = conn.execute(text(
                "SELECT p.name, COUNT(*) n FROM fact_sales_orders s JOIN dim_partners p ON p.id = s.partner_id "
                "WHERE s.tenant_id = CAST(:t AS uuid) AND s.state IN ('sale','done') "
                "GROUP BY p.name ORDER BY n DESC LIMIT 1"), {"t": _TENANT}).first()
        if not row:
            self.skipTest("no sales")
        res = self._rel(row[0])
        top = [m for m in res["matches"] if m["name"] == row[0]][0]
        self.assertIn("customer", top["role"])
        self.assertEqual(top["activity"]["sales_orders"]["count"], row[1])
        self.assertIn("customer", res["relationship"])





@unittest.skipUnless(_TENANT, "warehouse not reachable or empty")
class TenantProfileTests(SimpleTestCase):
    """Reads the configured warehouse (no writes)."""

    def test_profile_lists_real_categories_and_no_fixed_competitors(self):
        from doova_one_view.api.agent.tools_refactored.common import get_tenant_profile_tool

        profile = get_tenant_profile_tool(tenant_ids=[_TENANT])
        text = str(profile)
        for name in HARDCODED_NAMES:
            self.assertNotIn(name, text)
        for key in ("downstream_channel_note", "supply_chain_position", "commercial_tier"):
            self.assertNotIn(key, profile)
        cats = profile["sells_categories"]
        self.assertTrue(cats)
        expected = [c["category"] for c in profile["dynamic_revenue_study"]["top_product_categories"]]
        self.assertEqual(cats, expected)
        for c in cats:
            self.assertIn(c, profile["competitor_definition"])


# ── 2. layout ────────────────────────────────────────────────────────────────

class LayoutRuleTests(SimpleTestCase):
    def test_layout_rules_are_in_the_shared_instructions(self):
        rules = prompts.STATIC_AGENT_INSTRUCTIONS
        self.assertIn("LAYOUT", rules)
        self.assertIn("ends with a colon", rules)
        self.assertIn("go back to normal paragraphs", rules)
        self.assertIn("Never nest lists", rules)
        self.assertIn("Never repeat a table as a list", rules)
        self.assertNotIn("Break long explanations into clean bullet points", rules)

    def test_sql_tool_writes_findings_not_a_formatted_reply(self):
        p = prompts.SQL_FINAL_RESPONSE_PROMPT
        self.assertNotIn("**HEADLINE**", p)
        self.assertNotIn("**KEY NUMBERS**", p)
        self.assertIn("No headline", p)
        # still a valid format string with the three placeholders the agent fills
        filled = p.format(user_question="q", sql="SELECT 1", result_preview="[]")
        self.assertIn("SELECT 1", filled)

    def test_main_prompt_template_still_renders(self):
        from langchain_core.prompts import MessagesPlaceholder

        tpl = prompts.AGENT_SYSTEM_PROMPT
        message_slots = {m.variable_name for m in tpl.messages if isinstance(m, MessagesPlaceholder)}
        values = {v: ([] if v in message_slots else "x") for v in tpl.input_variables}
        messages = tpl.format_messages(**values)
        self.assertTrue(any("LAYOUT" in str(m.content) for m in messages))


class DisplayTableTests(SimpleTestCase):
    ROWS = [
        {"product_id": 6078, "product_name": "JAC T8 Pickup", "default_code": "false", "currency_code": "XAF",
         "total_subtotal": 43043478, "total_quantity_sold": 2},
        {"product_id": 3916, "product_name": "Ac hisense 12000 BTU R410", "default_code": False, "currency_code": "XAF",
         "total_subtotal": 26560000, "total_quantity_sold": 83},
    ]

    def test_ids_and_empty_columns_are_hidden_and_headers_are_readable(self):
        table = rows_to_markdown(rows_for_display(self.ROWS))
        header = table.splitlines()[0]
        self.assertEqual(header, "| Product name | Currency code | Total subtotal | Total quantity sold |")
        self.assertNotIn("6,078", table)
        self.assertNotIn("false", table.lower())
        self.assertIn("| JAC T8 Pickup | XAF | 43,043,478 | 2 |", table)

    def test_raw_rows_are_not_changed(self):
        rows_for_display(self.ROWS)
        self.assertEqual(self.ROWS[0]["product_id"], 6078)
        self.assertEqual(self.ROWS[0]["default_code"], "false")

    def test_a_table_of_ids_only_keeps_them(self):
        self.assertEqual(rows_for_display([{"id": 1}, {"id": 2}]), [{"ID": 1}, {"ID": 2}])

    def test_years_are_not_given_a_thousands_separator(self):
        table = rows_to_markdown(rows_for_display([{"year": 2026, "revenue": 1500}, {"year": 2025, "revenue": 900}]))
        self.assertIn("| 2026 | 1,500 |", table)

    def test_some_empty_values_in_a_useful_column_become_blank_cells(self):
        shown = rows_for_display([{"name": "A", "ref": "X1"}, {"name": "B", "ref": False}])
        self.assertEqual(shown[1]["Ref"], "")

    def test_empty(self):
        self.assertEqual(rows_for_display([]), [])


class WebAnswerJoiningTests(SimpleTestCase):
    """A cited web answer arrives as several text blocks that together form one text."""

    def _block(self, text, citations=None):
        from unittest.mock import MagicMock
        b = MagicMock()
        b.type = "text"
        b.text = text
        b.citations = citations or []
        return b

    def test_cited_pieces_are_joined_without_breaking_sentences(self):
        from unittest.mock import MagicMock, patch
        from doova_one_view.api.agent.web_search_agent import WebSearchAgent

        cite = MagicMock(url="https://example.com/dir", title="Directory", cited_text="refrigerators and freezers")
        response = MagicMock(stop_reason="end_turn")
        response.content = [
            self._block("It describes the category as "),
            self._block("refrigerators and freezers to washing machines", [cite]),
            self._block(". That is the category description.\n\nSecond paragraph."),
        ]
        agent = WebSearchAgent()
        agent.client = MagicMock()
        agent.client.messages.create.return_value = response
        with patch("doova_one_view.api.agent.utils.get_tenant_currency", return_value="XAF"):
            answer, citations = agent.run(
                message="What do appliance stores sell?", tenant_ids=["11111111-1111-4111-8111-111111111111"]
            )
        self.assertIn(
            "It describes the category as refrigerators and freezers to washing machines. That is the category description.",
            answer,
        )
        self.assertIn("\n\nSecond paragraph.", answer)  # real paragraph breaks are kept
        self.assertEqual(len(citations), 1)

    def test_currency_codes_stay_upper_case_in_table_headers(self):
        shown = rows_for_display([{"product_name": "A", "revenue_xaf": 10}, {"product_name": "B", "revenue_xaf": 20}])
        self.assertEqual(list(shown[0].keys()), ["Product name", "Revenue XAF"])
