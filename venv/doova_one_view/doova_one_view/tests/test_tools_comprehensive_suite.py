# doova_one_view/tests/test_tools_comprehensive_suite.py

import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "doova_one_view.settings")
django.setup()

import unittest
from unittest.mock import patch
from doova_one_view.api.agent.tools_refactored.common import (
    calculate_ratio,
    normalize_business_text_for_intent,
    get_tenant_profile_tool
)
from doova_one_view.api.agent.tools_refactored.inventory import get_inventory_efficiency_tool
from doova_one_view.api.agent.tools_refactored.finance import get_receivables_analysis_tool, get_business_health_score_tool

class TestToolsComprehensiveSuite(unittest.TestCase):

    def test_calculate_ratio_safe_zero_division(self):
        """Verify calculate_ratio handles division by zero safely without raising ZeroDivisionError."""
        ratio_zero = calculate_ratio(100.0, 0.0)
        self.assertEqual(ratio_zero, 0.0)

        ratio_normal = calculate_ratio(100.0, 25.0)
        self.assertEqual(ratio_normal, 4.0)

    def test_normalize_business_text_for_intent(self):
        """Verify text normalizer cleans business queries, lowercases, and fixes typos."""
        raw_query = "   What is my salse & revnue for 2026?  "
        clean = normalize_business_text_for_intent(raw_query)
        self.assertIn("sales", clean)
        self.assertIn("revenue", clean)

    @patch("doova_one_view.api.agent.tools_refactored.inventory.run_query")
    def test_get_inventory_efficiency_tool_empty_result(self, mock_run_query):
        """Verify inventory efficiency tool returns formatted dictionary when mock database returns data."""
        mock_run_query.side_effect = [
            [{"total_value": 10000.0}],  # inv_rows
            [{"move_value": 45000.0}]    # move_rows
        ]
        result = get_inventory_efficiency_tool(tenant_id="3fa85f64-5717-4562-b3fc-2c963f66afa6")
        self.assertIsInstance(result, dict)
        self.assertIn("turnover_ratio", result)
        self.assertEqual(result["turnover_ratio"], 4.5)

    @patch("doova_one_view.api.agent.tools_refactored.finance.run_query")
    def test_get_receivables_analysis_tool(self, mock_run_query):
        """Verify get_receivables_analysis_tool aggregates overdue invoices and AR totals."""
        mock_run_query.side_effect = [
            [{"total_receivables": 50000.0, "overdue": 12000.0}],  # summary query
            [{"partner_name": "Acme Corp", "overdue_amount": 12000.0}]  # breakdown query
        ]
        result = get_receivables_analysis_tool(tenant_id="3fa85f64-5717-4562-b3fc-2c963f66afa6")
        self.assertIsInstance(result, dict)
        self.assertEqual(result.get("total_receivables"), 50000.0)
        self.assertEqual(result.get("overdue_receivables"), 12000.0)

    @patch("doova_one_view.api.agent.tools_refactored.finance.get_inventory_efficiency_tool")
    @patch("doova_one_view.api.agent.tools_refactored.finance.get_receivables_analysis_tool")
    @patch("doova_one_view.api.agent.tools_refactored.finance.get_sales_summary_tool")
    def test_get_business_health_score_tool(self, mock_sales, mock_receivables, mock_inv):
        """Verify get_business_health_score_tool calculates composite health index and status."""
        mock_sales.return_value = {"total_revenue": 100000.0, "gross_margin": 30000.0}
        mock_receivables.return_value = {"overdue_receivables": 5000.0, "total_receivables": 50000.0, "overdue_ratio": 0.1}
        mock_inv.return_value = {"turnover_ratio": 4.5}

        result = get_business_health_score_tool(tenant_id="3fa85f64-5717-4562-b3fc-2c963f66afa6")
        self.assertIsInstance(result, dict)
        self.assertIn("business_health_score", result)
        self.assertIn("health_status", result)

if __name__ == "__main__":
    unittest.main()
