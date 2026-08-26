# doova_one_view/tests/test_tools_inventory.py

import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "doova_one_view.settings")
django.setup()

import unittest
from unittest.mock import patch, MagicMock
from doova_one_view.api.agent.tools_refactored.inventory import (
    get_inventory_alerts_tool,
    get_inventory_efficiency_tool,
    get_inventory_stock_table_tool,
    get_inventory_dashboard_alerts_tool,
    get_inventory_valuation_tool,
)

class TestInventoryTools(unittest.TestCase):

    @patch("doova_one_view.api.agent.tools_refactored.inventory.run_query")
    def test_get_inventory_alerts_tool(self, mock_run_query):
        mock_run_query.side_effect = [
            [{"product_name": "AC 12000 BTU", "available": 3.0, "location_name": "WH/Stock"}],
            [{"name": "LOT-001", "product_name": "Refrigerant Gas", "expiration_date": "2026-09-01"}]
        ]
        res = get_inventory_alerts_tool(tenant_id="default", low_stock_threshold=5)
        self.assertEqual(res["tool_name"], "get_inventory_alerts_tool")
        self.assertEqual(len(res["low_stock_items"]), 1)
        self.assertEqual(res["low_stock_items"][0]["product"], "AC 12000 BTU")

    @patch("doova_one_view.api.agent.tools_refactored.inventory.run_query")
    def test_get_inventory_efficiency_tool(self, mock_run_query):
        mock_run_query.side_effect = [
            [{"total_value": 100000.0, "sku_count": 50}],
            [{"move_value": 400000.0}]
        ]
        res = get_inventory_efficiency_tool(tenant_id="default")
        self.assertEqual(res["tool_name"], "get_inventory_efficiency_tool")
        self.assertEqual(res["total_inventory_value"], 100000.0)
        self.assertEqual(res["turnover_ratio"], 4.0)

    @patch("doova_one_view.api.inventory.service.InventoryService.get_stock_table")
    def test_get_inventory_stock_table_tool(self, mock_get_table):
        mock_get_table.return_value = {
            "table_type": "all",
            "total_count": 2423,
            "items": [{"id": 1, "product_name": "Air Conditioner", "quantity": 10}]
        }
        res = get_inventory_stock_table_tool(tenant_id="default", table_type="all")
        self.assertEqual(res["tool_name"], "get_inventory_stock_table_tool")
        self.assertEqual(res["total_count"], 2423)

    @patch("doova_one_view.api.inventory.service.InventoryService.get_alerts_sync")
    def test_get_inventory_dashboard_alerts_tool(self, mock_get_alerts):
        mock_get_alerts.return_value = {
            "out_of_stock_count": 2,
            "low_stock_count": 5,
            "expiring_soon_count": 0
        }
        res = get_inventory_dashboard_alerts_tool(tenant_id="default")
        self.assertEqual(res["tool_name"], "get_inventory_dashboard_alerts_tool")
        self.assertEqual(res["out_of_stock_count"], 2)

    @patch("doova_one_view.api.inventory.service.InventoryService.get_inventory_summary_sync")
    def test_get_inventory_valuation_tool(self, mock_get_summary):
        mock_get_summary.return_value = {
            "total_inventory_value": 2908401860.0,
            "total_products_in_stock": 2423
        }
        res = get_inventory_valuation_tool(tenant_id="default")
        self.assertEqual(res["tool_name"], "get_inventory_valuation_tool")
        self.assertEqual(res["total_inventory_value"], 2908401860.0)


if __name__ == "__main__":
    unittest.main()
