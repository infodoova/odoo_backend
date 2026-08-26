"""
doova_one_view/tests/test_domain_report_templates.py

Unit and integration tests for Domain-Specific Report Templates (Pro Plan v3 — Agent-Driven).
Tests template rendering, template routing, data normalization, chart rendering,
and backward compatibility.
"""

import uuid
from django.test import TestCase
from jinja2 import Environment, FileSystemLoader
from pathlib import Path

from odoo_app.models.tenant import Tenant
from doova_one_view.api.agent.tools_refactored.reporting_v2 import (
    generate_report_tool,
    _resolve_report_template,
    _normalize_report_data,
    _render_charts_from_report_data,
)
from doova_one_view.api.agent.tools_refactored.template_registry import (
    TEMPLATE_REGISTRY,
    get_template_metadata,
)
from doova_one_view.api.agent.langchain_tools import create_report


class DomainReportTemplatesTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(id=uuid.uuid4(), name="Domain Template Tenant")
        self.tenant_id = str(self.tenant.id)

    def test_all_templates_jinja2_compilation(self):
        """
        Verify all 12 domain templates + base template + health template parse cleanly in Jinja2.
        """
        template_dir = Path(__file__).resolve().parent.parent / "api" / "agent" / "tools_refactored" / "templates"
        env = Environment(loader=FileSystemLoader(str(template_dir)))

        expected_templates = [
            "_report_base.html",
            "sales_report.html",
            "purchase_report.html",
            "cashflow_report.html",
            "inventory_report.html",
            "income_statement_report.html",
            "balance_sheet_report.html",
            "financial_analysis_report.html",
            "monthly_pnl_report.html",
            "proforma_report.html",
            "consolidated_report.html",
            "accounting_report.html",
            "general_report.html",
            "report_template.html",
        ]

        for t in expected_templates:
            tpl = env.get_template(t)
            self.assertIsNotNone(tpl, f"Template {t} failed to load")

    def test_template_router_resolution(self):
        """
        Verify _resolve_report_template accurately routes keys, aliases, NLP keywords, and legacy fallbacks.
        """
        # 1. Exact canonical keys
        t_file, key, _ = _resolve_report_template("sales", "")
        self.assertEqual(t_file, "sales_report.html")
        self.assertEqual(key, "sales")

        t_file, key, _ = _resolve_report_template("purchase", "")
        self.assertEqual(t_file, "purchase_report.html")
        self.assertEqual(key, "purchase")

        t_file, key, _ = _resolve_report_template("inventory", "")
        self.assertEqual(t_file, "inventory_report.html")

        t_file, key, _ = _resolve_report_template("cashflow", "")
        self.assertEqual(t_file, "cashflow_report.html")

        # 2. Aliases
        t_file, key, _ = _resolve_report_template("commercial", "")
        self.assertEqual(t_file, "sales_report.html")

        t_file, key, _ = _resolve_report_template("stock", "")
        self.assertEqual(t_file, "inventory_report.html")

        t_file, key, _ = _resolve_report_template("pnl", "")
        self.assertEqual(t_file, "income_statement_report.html")

        # 3. NLP Prompt Keywords
        t_file, key, _ = _resolve_report_template("auto", "I need a balance sheet summary")
        self.assertEqual(t_file, "balance_sheet_report.html")

        t_file, key, _ = _resolve_report_template("auto", "Show me sales volume and top selling products")
        self.assertEqual(t_file, "sales_report.html")

        # 4. Backward compatibility fallback (None / empty string -> report_template.html)
        t_file, key, _ = _resolve_report_template(None, "")
        self.assertEqual(t_file, "report_template.html")
        self.assertEqual(key, "health")

    def test_normalize_report_data(self):
        """
        Verify _normalize_report_data wraps plain numbers and leaves formatted dicts intact.
        """
        raw_data = {
            "revenue": 1500000.0,
            "sales_volume": 450,
            "gross_profit": {
                "raw": 600000.0,
                "var_text": "+15%",
                "arrow": "▲",
                "var_class": "variance-positive",
            },
            "top_products": [{"name": "Widget A", "revenue": "100,000 XAF"}],
        }

        norm = _normalize_report_data(raw_data, currency="XAF")
        self.assertEqual(norm["revenue"]["raw"], 1500000.0)
        self.assertIn("1,500,000 XAF", norm["revenue"]["formatted"])
        self.assertEqual(norm["sales_volume"]["raw"], 450.0)
        self.assertEqual(norm["gross_profit"]["formatted"], "600,000 XAF")
        self.assertEqual(norm["gross_profit"]["var_text"], "+15%")
        self.assertEqual(len(norm["top_products"]), 1)

    def test_render_charts_from_report_data(self):
        """
        Verify _render_charts_from_report_data creates base64 charts from trend and waterfall data.
        """
        data = {
            "trend_data": [
                {"period": "Jan", "revenue": 100000, "expenses": 80000, "net_profit": 20000},
                {"period": "Feb", "revenue": 120000, "expenses": 85000, "net_profit": 35000},
                {"period": "Mar", "revenue": 150000, "expenses": 90000, "net_profit": 60000},
            ],
            "waterfall_data": {
                "revenue": 500000,
                "cogs": 200000,
                "gross_profit": 300000,
                "opex": 100000,
                "ebit": 200000,
                "net_profit": 180000,
            },
        }

        charts = _render_charts_from_report_data(data, currency="XAF")
        self.assertIn("chart_1_b64", charts)
        self.assertIn("chart_2_b64", charts)
        self.assertGreater(len(charts["chart_1_b64"]), 100)
        self.assertGreater(len(charts["chart_2_b64"]), 100)

    def test_agent_driven_sales_report_pdf_generation(self):
        """
        Verify generate_report_tool compiles sales_report.html cleanly from agent-supplied report_data.
        """
        report_data = {
            "revenue": {"raw": 2500000.0, "formatted": "2,500,000 XAF", "var_text": "+18.5%", "arrow": "▲", "var_class": "variance-positive"},
            "sales_volume": {"raw": 1200, "formatted": "1,200 Units"},
            "avg_order_value": {"raw": 2083.0, "formatted": "2,083 XAF"},
            "top_products": [
                {"name": "Product Alpha", "qty": 500, "revenue": "1,200,000 XAF", "margin": "45%"},
                {"name": "Product Beta", "qty": 350, "revenue": "800,000 XAF", "margin": "38%"},
            ],
            "top_customers": [
                {"name": "Customer Global Ltd", "orders": 12, "revenue": "950,000 XAF", "share": "38%"},
            ],
        }

        result = generate_report_tool(
            tenant_id=self.tenant_id,
            custom_content="## Commercial Performance\nStrong volume growth observed in Q2.",
            report_type="sales",
            report_data=report_data,
        )

        self.assertEqual(result["status"], "success")
        self.assertTrue(result["filename"].endswith(".pdf"))
        self.assertIn("download_url", result)

    def test_agent_driven_inventory_report_pdf_generation(self):
        """
        Verify generate_report_tool compiles inventory_report.html cleanly with partial data.
        """
        report_data = {
            "inventory_value": {"raw": 4500000.0, "formatted": "4,500,000 XAF"},
            "low_stock_alerts": [
                {"name": "Item X", "qty": 2, "min_qty": 10},
                {"name": "Item Y", "qty": 0, "min_qty": 5},
            ],
        }

        result = generate_report_tool(
            tenant_id=self.tenant_id,
            custom_content="## Warehouse Audit\nReorder threshold alerts flagged for Item X and Y.",
            report_type="inventory",
            report_data=report_data,
        )

        self.assertEqual(result["status"], "success")
        self.assertTrue(result["filename"].endswith(".pdf"))

    def test_backward_compatibility_health_report_generation(self):
        """
        Verify generate_report_tool runs legacy path when report_data is None and report_type is default/None.
        """
        result = generate_report_tool(
            tenant_id=self.tenant_id,
            custom_content="## Health Summary\nLegacy health analysis.",
        )

        self.assertEqual(result["status"], "success")
        self.assertTrue(result["filename"].endswith(".pdf"))

    def test_create_report_langchain_tool_with_report_type_and_data(self):
        """
        Verify create_report tool signature accepts report_type and report_data and returns success markdown link.
        """
        res_str = create_report.invoke({
            "tenant_id": self.tenant_id,
            "custom_content": "## Pro Forma Outlook\nProjecting 20% growth next quarter.",
            "report_type": "proforma",
            "report_data": {
                "projected_revenue": {"raw": 5000000.0, "formatted": "5,000,000 XAF"},
                "projected_growth": {"raw": 20.0, "formatted": "+20.0%"},
            },
        })

        self.assertIn("SUCCESS!", res_str)
        self.assertIn("[📥 **Download Full PDF Report**]", res_str)
        self.assertIn(".pdf", res_str)

    def test_report_type_classifier_direct_normalization(self):
        """
        Verify ReportTypeClassifier.normalize_report_type accurately maps aliases to canonical keys.
        """
        from doova_one_view.api.agent.report_classifier import ReportTypeClassifier

        self.assertEqual(ReportTypeClassifier.normalize_report_type("commercial"), "sales")
        self.assertEqual(ReportTypeClassifier.normalize_report_type("procurement"), "purchase")
        self.assertEqual(ReportTypeClassifier.normalize_report_type("stock"), "inventory")
        self.assertEqual(ReportTypeClassifier.normalize_report_type("liquidity"), "cashflow")
        self.assertEqual(ReportTypeClassifier.normalize_report_type("pnl"), "income_statement")
        self.assertEqual(ReportTypeClassifier.normalize_report_type("forecast"), "proforma")
        self.assertEqual(ReportTypeClassifier.normalize_report_type("health"), "health")
        self.assertEqual(ReportTypeClassifier.normalize_report_type(None), "health")

    def test_report_type_classifier_keyword_scoring(self):
        """
        Verify ReportTypeClassifier.classify accurately scores text intents in Tier 1.
        """
        from doova_one_view.api.agent.report_classifier import ReportTypeClassifier

        # Sales intent
        res = ReportTypeClassifier.classify(prompt="I need a sales report with top products and customer revenue")
        self.assertEqual(res, "sales")

        # Inventory intent
        res = ReportTypeClassifier.classify(prompt="Check warehouse stock valuation, low stock alerts, and turnover")
        self.assertEqual(res, "inventory")

        # Cashflow intent
        res = ReportTypeClassifier.classify(prompt="Show me our bank balance and cash flow liquidity breakdown")
        self.assertEqual(res, "cashflow")

        # Proforma intent
        res = ReportTypeClassifier.classify(prompt="Build a pro forma forward forecast with bull and bear scenarios")
        self.assertEqual(res, "proforma")

        # Balance sheet intent
        res = ReportTypeClassifier.classify(prompt="Give me a balance sheet summary of assets, liabilities, and equity")
        self.assertEqual(res, "balance_sheet")

        # Backward compatibility fallback
        res = ReportTypeClassifier.classify(prompt="")
        self.assertEqual(res, "health")

    def test_report_data_json_contract_pydantic_validation(self):
        """
        Verify ReportDataContract Pydantic schema parses, validates, and serializes report_data JSON.
        """
        from doova_one_view.api.agent.schemas import (
            ReportDataContract,
            KPICardValue,
            ProductRow,
            TrendDataPoint,
            WaterfallData,
        )

        payload = {
            "revenue": {
                "raw": 3500000.0,
                "formatted": "3,500,000 XAF",
                "var_text": "+15.0%",
                "arrow": "▲",
                "var_class": "variance-positive",
            },
            "sales_volume": 1200,
            "top_products": [
                {"name": "Solar Kit", "qty": 40, "revenue": "1,200,000 XAF", "margin": "45%"},
            ],
            "trend_data": [
                {"period": "Jan", "revenue": 100000, "expenses": 80000, "net_profit": 20000},
            ],
            "waterfall_data": {
                "revenue": 500000,
                "cogs": 200000,
                "gross_profit": 300000,
                "opex": 100000,
                "ebit": 200000,
                "tax": 20000,
                "net_profit": 180000,
            },
            "custom_domain_meta": "allowed-by-extra-config",
        }

        contract = ReportDataContract.from_payload(payload)
        self.assertIsInstance(contract.revenue, KPICardValue)
        self.assertEqual(contract.revenue.raw, 3500000.0)
        self.assertEqual(contract.revenue.var_text, "+15.0%")
        self.assertEqual(len(contract.top_products), 1)
        self.assertEqual(contract.top_products[0].name, "Solar Kit")
        self.assertIsInstance(contract.waterfall_data, WaterfallData)

        template_dict = contract.to_template_dict()
        self.assertIn("revenue", template_dict)
        self.assertIn("trend_data", template_dict)
        self.assertEqual(template_dict["custom_domain_meta"], "allowed-by-extra-config")
