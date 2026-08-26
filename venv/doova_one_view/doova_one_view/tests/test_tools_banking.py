# doova_one_view/tests/test_tools_banking.py

import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "doova_one_view.settings")
django.setup()

import unittest
from unittest.mock import patch
from doova_one_view.api.agent.tools_refactored.banking import (
    get_bank_cash_summary_tool,
    get_journal_cards_tool,
    get_bank_statement_summary_tool,
)

class TestBankingTools(unittest.TestCase):

    @patch("doova_one_view.api.agent.tools_refactored.banking.run_query")
    def test_get_bank_cash_summary_tool(self, mock_run_query):
        mock_run_query.return_value = [
            {"account_name": "BGFI Bank Main XAF", "balance": 450000000.0, "currency": "XAF"}
        ]
        res = get_bank_cash_summary_tool(tenant_id="default")
        self.assertEqual(res["tool_name"], "get_bank_cash_summary_tool")

    @patch("doova_one_view.api.agent.tools_refactored.banking.run_query")
    def test_get_journal_cards_tool(self, mock_run_query):
        mock_run_query.return_value = [
            {"journal_name": "Customer Invoices", "total_balance": 150000000.0}
        ]
        res = get_journal_cards_tool(tenant_id="default")
        self.assertEqual(res["tool_name"], "get_journal_cards_tool")

    @patch("doova_one_view.api.agent.tools_refactored.banking.run_query")
    def test_get_bank_statement_summary_tool(self, mock_run_query):
        mock_run_query.return_value = [
            {"statement_name": "ST-2026-08", "balance": 450000000.0, "line_count": 35}
        ]
        res = get_bank_statement_summary_tool(tenant_id="default")
        self.assertEqual(res["tool_name"], "get_bank_statement_summary_tool")

if __name__ == "__main__":
    unittest.main()
