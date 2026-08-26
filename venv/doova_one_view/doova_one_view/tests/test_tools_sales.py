# doova_one_view/tests/test_tools_sales.py

import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "doova_one_view.settings")
django.setup()

import unittest
from unittest.mock import patch
from doova_one_view.api.agent.tools_refactored.sales import (
    get_sales_summary_tool,
    get_top_products_tool,
    get_time_series_data_tool,
    get_sales_chart_data_tool,
    analyze_variance_tool,
    forecast_sales_tool,
)

class TestSalesTools(unittest.TestCase):

    @patch("doova_one_view.api.agent.tools_refactored.sales.run_query")
    def test_get_sales_summary_tool(self, mock_run_query):
        mock_run_query.return_value = [{"total_revenue": 250000.0, "order_count": 50, "average_order_value": 5000.0}]
        res = get_sales_summary_tool(tenant_id="default", start_date="2026-01-01", end_date="2026-08-06")
        self.assertEqual(res["tool_name"], "get_sales_summary_tool")
        self.assertEqual(res["total_revenue"], 250000.0)
        self.assertEqual(res["order_count"], 50)

    @patch("doova_one_view.api.agent.tools_refactored.sales.run_query")
    def test_get_top_products_tool(self, mock_run_query):
        mock_run_query.return_value = [
            {"product_name": "AC Unit 18000 BTU", "quantity": 100.0, "revenue": 300000.0},
            {"product_name": "JETOUR SUV", "quantity": 3.0, "revenue": 600000.0}
        ]
        res = get_top_products_tool(tenant_id="default", limit=5)
        self.assertEqual(res["tool_name"], "get_top_products_tool")
        self.assertEqual(len(res["products"]), 2)
        self.assertEqual(res["products"][0]["product"], "AC Unit 18000 BTU")

    @patch("doova_one_view.api.agent.tools_refactored.sales.run_query")
    def test_get_time_series_data_tool(self, mock_run_query):
        mock_run_query.return_value = [
            {"period": "2026-01", "revenue": 100000.0, "order_count": 20},
            {"period": "2026-02", "revenue": 150000.0, "order_count": 30}
        ]
        res = get_time_series_data_tool(tenant_id="default", granularity="month")
        self.assertEqual(res["tool_name"], "get_time_series_data_tool")
        self.assertEqual(len(res["points"]), 2)

    @patch("doova_one_view.api.agent.tools_refactored.sales.get_time_series_data_tool")
    def test_get_sales_chart_data_tool(self, mock_time_series):
        mock_time_series.return_value = {
            "tool_name": "get_time_series_data_tool",
            "points": [{"period": "2026-01", "revenue": 100000.0}]
        }
        res = get_sales_chart_data_tool(tenant_id="default")
        self.assertEqual(res["tool_name"], "get_sales_chart_data_tool")

    @patch("doova_one_view.api.agent.tools_refactored.sales.run_query")
    def test_analyze_variance_tool(self, mock_run_query):
        mock_run_query.return_value = [
            {"month": "2026-08-01", "revenue": 200000.0},
            {"month": "2026-07-01", "revenue": 150000.0}
        ]
        res = analyze_variance_tool(tenant_id="default")
        self.assertEqual(res["tool_name"], "analyze_variance_tool")
        self.assertEqual(res["change"], 50000.0)

    @patch("doova_one_view.api.agent.tools_refactored.sales.run_query")
    def test_forecast_sales_tool(self, mock_run_query):
        mock_run_query.return_value = [
            {"month": "2026-07-01", "revenue": 150000.0},
            {"month": "2026-08-01", "revenue": 180000.0}
        ]
        res = forecast_sales_tool(tenant_id="default")
        self.assertEqual(res["tool_name"], "forecast_sales_tool")

if __name__ == "__main__":
    unittest.main()
