"""
doova_one_view/tests/test_report_rendering_and_export.py

Tier 3: Document Compilation & Excel Formula Verification.
Verifies WeasyPrint PDF layout generation, OpenPyXL active formula spreadsheets,
and tenant threshold configurations.
"""

import uuid
from decimal import Decimal
import openpyxl
import io
from django.test import TestCase

from odoo_app.models.tenant import Tenant
from odoo_app.models.tenant_financial_mapping import TenantFinancialMapping
from doova_one_view.api.agent.tools_refactored.reporting_v2 import generate_report_tool
from doova_one_view.api.agent.excel_exporter import ExcelReportExporter
from doova_one_view.api.agent.thresholds import get_tenant_thresholds


class ReportRenderingAndExportTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(id=uuid.uuid4(), name="Export Test Tenant")

    def test_tenant_threshold_customization(self):
        """
        Verify tenant-configurable thresholds in TenantFinancialMapping.
        """
        TenantFinancialMapping.objects.create(
            tenant=self.tenant,
            variance_warning_threshold_pct=Decimal("3.50"),
            variance_critical_threshold_pct=Decimal("12.00"),
            po_matching_tolerance_pct=Decimal("0.75"),
            min_completeness_threshold_pct=Decimal("95.00"),
        )

        thresholds = get_tenant_thresholds(str(self.tenant.id))
        self.assertEqual(thresholds["variance_warning_threshold_pct"], 3.50)
        self.assertEqual(thresholds["variance_critical_threshold_pct"], 12.00)
        self.assertEqual(thresholds["po_matching_tolerance_pct"], 0.75)
        self.assertEqual(thresholds["min_completeness_threshold_pct"], 95.00)

    def test_excel_exporter_active_formulas_and_styling(self):
        """
        Verify that ExcelReportExporter produces valid .xlsx files with active SUM formulas
        and soft cell fill colors.
        """
        kpis = {
            "revenue": {"raw": 1000000.0, "formatted": "1,000,000 XAF", "var_text": "+10%"},
            "net_profit": {"raw": 250000.0, "formatted": "250,000 XAF", "var_text": "+5%"},
        }
        pnl = {
            "revenue": 1000000.0,
            "cogs": 400000.0,
            "operating_expenses": 350000.0,
            "other_income": 0.0,
        }

        xlsx_bytes = ExcelReportExporter.generate_financial_workbook(
            company_name="Test Enterprise",
            currency="XAF",
            kpis=kpis,
            pnl_data=pnl
        )

        self.assertGreater(len(xlsx_bytes), 1000)

        # Inspect workbook structure
        wb = openpyxl.load_workbook(io.BytesIO(xlsx_bytes))
        self.assertIn("Executive Summary", wb.sheetnames)
        self.assertIn("Income Statement", wb.sheetnames)
        self.assertIn("Working Capital & Audit", wb.sheetnames)

        ws_pnl = wb["Income Statement"]
        # Verify active formula cell
        formula_val = ws_pnl["B9"].value
        self.assertTrue(str(formula_val).startswith("=SUM("))

    def test_pdf_report_tool_generation(self):
        """
        Verify generate_report_tool compiles cleanly to PDF.
        """
        res = generate_report_tool(
            tenant_id=str(self.tenant.id),
            custom_content="## Audit Overview\nAll accounts reconciled cleanly.",
            report_mode="executive_brief"
        )
        self.assertEqual(res["tool_name"], "generate_report_tool")
        self.assertEqual(res.get("status"), "success")
        self.assertTrue(res["filename"].endswith(".pdf"))

    def test_variance_computation_helper(self):
        """
        Verify _compute_variance handles positive, negative, and zero baseline math.
        """
        from doova_one_view.api.agent.tools_refactored.reporting_v2 import _compute_variance
        # 100 vs 80 -> +25%
        pct, delta = _compute_variance(100.0, 80.0)
        self.assertEqual(pct, 25.0)
        self.assertEqual(delta, 20.0)

        # 50 vs 100 -> -50%
        pct, delta = _compute_variance(50.0, 100.0)
        self.assertEqual(pct, -50.0)
        self.assertEqual(delta, -50.0)

        # Zero baseline
        pct, delta = _compute_variance(100.0, 0.0)
        self.assertEqual(pct, 100.0)
        self.assertEqual(delta, 100.0)

    def test_strip_json_chart_fenced_and_bare(self):
        """
        Verify strip_json_chart_from_text cleanly removes fenced, bare, and truncated chart JSON.
        """
        from doova_one_view.api.agent.utils import strip_json_chart_from_text, parse_json_chart_from_text

        # 1. Fenced JSON block
        text_with_fenced = (
            "Here is the monthly analysis.\n\n"
            "```json\n"
            '{"type": "chart", "message": "Trend chart", "chart": {"chartType": "line", "data": []}}\n'
            "```\n\n"
            "[📥 **Download Full PDF Report**](/reports/test.pdf)"
        )
        cleaned_fenced = strip_json_chart_from_text(text_with_fenced)
        self.assertNotIn('{"type": "chart"', cleaned_fenced)
        self.assertIn("Here is the monthly analysis.", cleaned_fenced)
        self.assertIn("[📥 **Download Full PDF Report**](/reports/test.pdf)", cleaned_fenced)

        # 2. Bare JSON block
        text_with_bare = (
            "Executive summary completed.\n\n"
            '{"type": "chart", "message": "Sales summary", "chart": {"chartType": "bar", "data": []}}\n'
            "[📥 **Download Full PDF Report**](/reports/test.pdf)"
        )
        cleaned_bare = strip_json_chart_from_text(text_with_bare)
        self.assertNotIn('{"type": "chart"', cleaned_bare)
        self.assertIn("Executive summary completed.", cleaned_bare)

        # 3. Truncated chart JSON fragment at the end
        text_with_fragment = (
            "Sales performance summary.\n\n"
            '{"type": "chart", "message": "Monthly revenue shows a dip", "chart": {'
        )
        cleaned_fragment = strip_json_chart_from_text(text_with_fragment)
        self.assertNotIn('{"type": "chart"', cleaned_fragment)
        self.assertEqual(cleaned_fragment, "Sales performance summary.")

    def test_normalize_markdown_tables_collapsed_and_prefixed(self):
        """
        Verify _normalize_markdown_tables expands single-line collapsed tables into valid markdown tables.
        """
        import markdown
        from doova_one_view.api.agent.tools_refactored.reporting_v2 import _normalize_markdown_tables

        s1 = "AR Aging Buckets: | Bucket | Amount | |---|---| | Current | XAF 0 | | 1–30 days | XAF 0 | | 31–60 days | XAF 0 | | 61–90 days | XAF 41,561,012 | | 90+ days | XAF 491,784,145 |"
        normalized1 = _normalize_markdown_tables(s1)
        html1 = markdown.markdown(normalized1, extensions=['tables'])
        self.assertIn("<table>", html1)
        self.assertIn("<th>Bucket</th>", html1)
        self.assertIn("<th>Amount</th>", html1)
        self.assertIn("<td>61–90 days</td>", html1)

        s2 = "Top Overdue Customers: | Customer | Overdue Amount | |---|---| | Seguibat S.A | XAF 195,642,207 | | Construction Company | XAF 105,432,133 |"
        normalized2 = _normalize_markdown_tables(s2)
        html2 = markdown.markdown(normalized2, extensions=['tables'])
        self.assertIn("<table>", html2)
        self.assertIn("<td>Seguibat S.A</td>", html2)


