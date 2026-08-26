# doova_one_view/tests/test_tools_financial.py

import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "doova_one_view.settings")
django.setup()

import unittest
from unittest.mock import patch, MagicMock
from doova_one_view.api.agent.tools_refactored.sales import get_sales_summary_tool, get_top_products_tool
from doova_one_view.api.agent.tools_refactored.inventory import get_inventory_efficiency_tool
from doova_one_view.api.agent.tools_refactored.finance import (
    get_receivables_analysis_tool,
    get_business_health_score_tool,
)

class TestFinancialTools(unittest.TestCase):

    @patch("doova_one_view.api.agent.tools_refactored.sales.run_query")
    def test_get_sales_summary_tool(self, mock_run_query):
        mock_run_query.return_value = [{"total_revenue": 150000.0, "order_count": 42, "average_order_value": 3571.4}]
        res = get_sales_summary_tool(tenant_id="default", start_date="2026-01-01", end_date="2026-08-06")
        self.assertEqual(res["tool_name"], "get_sales_summary_tool")
        self.assertEqual(res["total_revenue"], 150000.0)
        self.assertEqual(res["order_count"], 42)

    @patch("doova_one_view.api.agent.tools_refactored.sales.run_query")
    def test_get_top_products_tool(self, mock_run_query):
        mock_run_query.return_value = [
            {"product_name": "Air Conditioner 12000 BTU", "quantity": 50.0, "revenue": 125000.0},
            {"product_name": "JETOUR SUV", "quantity": 2.0, "revenue": 400000.0}
        ]
        res = get_top_products_tool(tenant_id="default", limit=5)
        self.assertEqual(res["tool_name"], "get_top_products_tool")
        self.assertEqual(len(res["products"]), 2)
        self.assertEqual(res["products"][0]["product"], "Air Conditioner 12000 BTU")

    @patch("doova_one_view.api.agent.tools_refactored.inventory.run_query")
    def test_get_inventory_efficiency_tool(self, mock_run_query):
        mock_run_query.side_effect = [
            [{"total_value": 50000.0, "sku_count": 100}],
            [{"move_value": 200000.0}]
        ]
        res = get_inventory_efficiency_tool(tenant_id="default")
        self.assertEqual(res["tool_name"], "get_inventory_efficiency_tool")
        self.assertEqual(res["total_inventory_value"], 50000.0)
        self.assertEqual(res["turnover_ratio"], 4.0)
        self.assertAlmostEqual(res["days_inventory_on_hand"], 91.25, places=2)

    @patch("doova_one_view.api.agent.tools_refactored.finance.run_query")
    def test_get_receivables_analysis_tool(self, mock_run_query):
        mock_run_query.side_effect = [
            [{"total_receivables": 80000.0, "overdue": 25000.0}],
            [{"partner_name": "Customer A", "overdue_amount": 15000.0}]
        ]
        res = get_receivables_analysis_tool(tenant_id="default")
        self.assertEqual(res["tool_name"], "get_receivables_analysis_tool")
        self.assertEqual(res["total_receivables"], 80000.0)
        self.assertEqual(res["overdue_receivables"], 25000.0)

    @patch("doova_one_view.api.agent.tools_refactored.finance.get_financial_ratios_tool")
    def test_get_business_health_score_tool(self, mock_get_ratios):
        mock_get_ratios.return_value = {
            "current_ratio": 2.1,
            "quick_ratio": 1.5,
            "gross_profit_margin": 0.45,
            "net_profit_margin": 0.15,
            "debt_to_equity": 0.5
        }
        res = get_business_health_score_tool(tenant_id="default")
        self.assertEqual(res["tool_name"], "get_business_health_score_tool")
        self.assertIn("business_health_score", res)
        self.assertGreaterEqual(res["business_health_score"], 0)
        self.assertLessEqual(res["business_health_score"], 100)

if __name__ == "__main__":
    unittest.main()
