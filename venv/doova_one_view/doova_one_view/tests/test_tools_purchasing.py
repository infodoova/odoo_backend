# doova_one_view/tests/test_tools_purchasing.py

import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "doova_one_view.settings")
django.setup()

import unittest
from unittest.mock import patch
from doova_one_view.api.agent.tools_refactored.purchasing import (
    get_purchase_summary_tool,
    get_top_vendors_tool,
    get_vendor_performance_tool,
    get_procurement_category_breakdown_tool,
    get_purchase_vs_sales_margin_tool,
)

class TestPurchasingTools(unittest.TestCase):

    @patch("doova_one_view.api.agent.tools_refactored.purchasing.run_query")
    def test_get_purchase_summary_tool(self, mock_run_query):
        mock_run_query.return_value = [{"total_spend": 1800000.0, "po_count": 25, "avg_po_value": 72000.0, "first_po_date": "2026-01-01", "last_po_date": "2026-08-01"}]
        res = get_purchase_summary_tool(tenant_id="default")
        self.assertEqual(res["tool_name"], "get_purchase_summary_tool")
        self.assertEqual(res["total_spend"], 1800000.0)
        self.assertEqual(res["po_count"], 25)

    @patch("doova_one_view.api.agent.tools_refactored.purchasing.run_query")
    def test_get_top_vendors_tool(self, mock_run_query):
        mock_run_query.return_value = [
            {"vendor_name": "JETOUR Auto China", "total_spend": 1200000.0, "po_count": 8, "avg_po_value": 150000.0},
            {"vendor_name": "AC Manufacturing Co", "total_spend": 600000.0, "po_count": 17, "avg_po_value": 35294.1}
        ]
        res = get_top_vendors_tool(tenant_id="default", limit=5)
        self.assertEqual(res["tool_name"], "get_top_vendors_tool")
        self.assertEqual(len(res["vendors"]), 2)
        self.assertEqual(res["vendors"][0]["vendor"], "JETOUR Auto China")

    @patch("doova_one_view.api.agent.tools_refactored.purchasing.run_query")
    def test_get_vendor_performance_tool(self, mock_run_query):
        mock_run_query.return_value = [
            {"vendor_name": "Supplier X", "total_spend": 500000.0, "po_count": 5, "receipts_total": 5, "receipts_on_time": 5, "avg_lead_time_days": 3.5}
        ]
        res = get_vendor_performance_tool(tenant_id="default")
        self.assertEqual(res["tool_name"], "get_vendor_performance_tool")
        self.assertEqual(res["vendors"][0]["vendor"], "Supplier X")

    @patch("doova_one_view.api.agent.tools_refactored.purchasing.run_query")
    def test_get_procurement_category_breakdown_tool(self, mock_run_query):
        mock_run_query.return_value = [
            {"category": "Automobiles", "spend": 1200000.0, "line_count": 14}
        ]
        res = get_procurement_category_breakdown_tool(tenant_id="default")
        self.assertEqual(res["tool_name"], "get_procurement_category_breakdown_tool")
        self.assertEqual(res["total_spend"], 1200000.0)

    @patch("doova_one_view.api.agent.tools_refactored.purchasing.run_query")
    def test_get_purchase_vs_sales_margin_tool(self, mock_run_query):
        mock_run_query.return_value = [
            {"product": "AC Unit 12000 BTU", "purchase_cost": 80000.0, "sales_revenue": 120000.0, "qty_purchased": 10.0, "qty_sold": 10.0}
        ]
        res = get_purchase_vs_sales_margin_tool(tenant_id="default")
        self.assertEqual(res["tool_name"], "get_purchase_vs_sales_margin_tool")

if __name__ == "__main__":
    unittest.main()
