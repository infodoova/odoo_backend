# doova_one_view/tests/test_tools_common.py

import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "doova_one_view.settings")
django.setup()

import unittest
from unittest.mock import patch
from doova_one_view.api.agent.tools_refactored.common import (
    normalize_business_text_for_intent,
    is_graph_request,
    get_tenant_profile_tool,
)

class TestToolsCommon(unittest.TestCase):

    def test_normalize_business_text_typos(self):
        self.assertEqual(normalize_business_text_for_intent("get revnue and salse"), "get revenue and sales")
        self.assertEqual(normalize_business_text_for_intent("check inventry stok"), "check inventory stock")
        self.assertEqual(normalize_business_text_for_intent("show me chrt for prodcut"), "show me chart for product")

    def test_is_graph_request(self):
        self.assertTrue(is_graph_request("plot revenue for 2026"))
        self.assertTrue(is_graph_request("show me a chart of sales"))
        self.assertFalse(is_graph_request("what is our total profit?"))

    @patch("doova_one_view.api.agent.tools_refactored.common.run_query")
    def test_get_tenant_profile_tool_dynamic_study(self, mock_run_query):
        # Mock companies query
        mock_run_query.side_effect = [
            [{"name": "SUPERNOVA,S.L.", "industry": "Not Specified", "type": "Not Specified", "currency": "XAF"}],
            [{"ptype": "consu", "sku_count": 2423}, {"ptype": "service", "sku_count": 18}],
            [{"ptype": "consu", "line_count": 3337, "total_revenue": 2908401860.0}],
            [{"category_name": "Trade Goods / Air Conditioner", "category_revenue": 1251290274.0, "category_lines": 482}]
        ]

        result = get_tenant_profile_tool(tenant_id="default")
        self.assertEqual(result["tool_name"], "get_tenant_profile_tool")
        self.assertIn("Dynamic CONSU-Dominant Business", result["inferred_business_model"])
        self.assertEqual(result["dynamic_revenue_study"]["total_revenue_analyzed"], 2908401860.0)

if __name__ == "__main__":
    unittest.main()
