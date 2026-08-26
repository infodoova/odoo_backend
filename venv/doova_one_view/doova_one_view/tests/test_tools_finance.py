# doova_one_view/tests/test_tools_finance.py

import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "doova_one_view.settings")
django.setup()

import unittest
from unittest.mock import patch
from doova_one_view.api.agent.tools_refactored.finance import (
    get_receivables_analysis_tool,
    get_payables_analysis_tool,
    get_expense_breakdown_tool,
    get_tax_summary_tool,
    detect_anomalies_tool,
    calculate_pnl_tool,
    get_balance_sheet_tool,
    get_business_health_score_tool,
)

class TestFinanceTools(unittest.TestCase):

    @patch("doova_one_view.api.agent.tools_refactored.finance.run_query")
    def test_get_receivables_analysis_tool(self, mock_run_query):
        mock_run_query.side_effect = [
            [{"total_receivables": 120000.0, "overdue": 30000.0}],
            [{"partner_name": "ACME Corp", "overdue_amount": 30000.0}]
        ]
        res = get_receivables_analysis_tool(tenant_id="default")
        self.assertEqual(res["tool_name"], "get_receivables_analysis_tool")
        self.assertEqual(res["total_receivables"], 120000.0)

    @patch("doova_one_view.api.agent.tools_refactored.finance.run_query")
    def test_get_payables_analysis_tool(self, mock_run_query):
        mock_run_query.side_effect = [
            [{"total_payables": 90000.0, "overdue": 15000.0}],
            [{"partner_name": "Supplier X", "overdue_amount": 15000.0}]
        ]
        res = get_payables_analysis_tool(tenant_id="default")
        self.assertEqual(res["tool_name"], "get_payables_analysis_tool")
        self.assertEqual(res["total_payables"], 90000.0)

    @patch("doova_one_view.api.agent.tools_refactored.finance.run_query")
    def test_get_expense_breakdown_tool(self, mock_run_query):
        mock_run_query.return_value = [
            {"account_name": "Rent", "amount": 50000.0},
            {"account_name": "Utilities", "amount": 12000.0}
        ]
        res = get_expense_breakdown_tool(tenant_id="default")
        self.assertEqual(res["tool_name"], "get_expense_breakdown_tool")

    @patch("doova_one_view.api.agent.tools_refactored.finance.run_query")
    def test_get_tax_summary_tool(self, mock_run_query):
        mock_run_query.return_value = [
            {"tax_name": "VAT 18%", "tax_collected": 45000.0, "tax_paid": 20000.0}
        ]
        res = get_tax_summary_tool(tenant_id="default")
        self.assertEqual(res["tool_name"], "get_tax_summary_tool")

    @patch("doova_one_view.api.agent.tools_refactored.finance.run_query")
    def test_detect_anomalies_tool(self, mock_run_query):
        mock_run_query.side_effect = [[], [], [], [], []]
        res = detect_anomalies_tool(tenant_id="default")
        self.assertEqual(res["tool_name"], "detect_anomalies_tool")

    @patch("doova_one_view.api.agent.tools_refactored.finance.run_query")
    def test_calculate_pnl_tool(self, mock_run_query):
        mock_run_query.return_value = [
            {"total_income": 600000.0, "cogs": 350000.0, "opex": 120000.0, "total_expenses": 470000.0}
        ]
        res = calculate_pnl_tool(tenant_id="default")
        self.assertEqual(res["tool_name"], "calculate_pnl_tool")
        self.assertEqual(res["gross_profit"], 250000.0)

    @patch("doova_one_view.api.agent.tools_refactored.finance.run_query")
    def test_get_balance_sheet_tool(self, mock_run_query):
        mock_run_query.side_effect = [
            [{"total_assets": 1000000.0}],
            [{"total_liabilities": 400000.0}],
            [{"equity": 600000.0}]
        ]
        res = get_balance_sheet_tool(tenant_id="default")
        self.assertEqual(res["tool_name"], "get_balance_sheet_tool")

    @patch("doova_one_view.api.agent.tools_refactored.finance.get_financial_ratios_tool")
    def test_get_business_health_score_tool(self, mock_ratios):
        mock_ratios.return_value = {
            "current_ratio": 2.5,
            "quick_ratio": 1.8,
            "gross_profit_margin": 0.5,
            "net_profit_margin": 0.2,
            "debt_to_equity": 0.4
        }
        res = get_business_health_score_tool(tenant_id="default")
        self.assertEqual(res["tool_name"], "get_business_health_score_tool")
        self.assertIn("business_health_score", res)

if __name__ == "__main__":
    unittest.main()
