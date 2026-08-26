# doova_one_view/tests/test_anomaly_unification.py

import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "doova_one_view.settings")
django.setup()

from django.test import TestCase
from unittest.mock import patch
from doova_one_view.api.agent.tools_refactored.finance import detect_anomalies_tool
from doova_one_view.api.jobs.alert_prechecks import run_all_prechecks


class TestAnomalyUnification(TestCase):

    @patch("doova_one_view.api.agent.tools_refactored.finance.run_query")
    @patch("doova_one_view.api.jobs.alert_prechecks.run_all_prechecks")
    def test_detect_anomalies_tool_includes_macro_prechecks(self, mock_prechecks, mock_query):
        mock_prechecks.return_value = {
            "any_triggered": True,
            "triggered_checks": ["cash_drop"],
            "precheck_summary": "• Cash balance dropped 25%",
        }
        mock_query.return_value = []

        res = detect_anomalies_tool(tenant_id="test-tenant")
        self.assertEqual(res["tool_name"], "detect_anomalies_tool")
        self.assertIn("macro_prechecks", res)
        self.assertTrue(res["macro_prechecks"]["any_triggered"])
        self.assertEqual(res["risk_level"], "High")
        mock_prechecks.assert_called_once()

    @patch("doova_one_view.api.jobs.alert_prechecks.run_query")
    def test_run_all_prechecks_includes_audit_checks(self, mock_query):
        mock_query.return_value = []
        res = run_all_prechecks(tenant_id="test-tenant")
        self.assertIn("any_triggered", res)
        self.assertIn("triggered_checks", res)
        self.assertIn("precheck_summary", res)


if __name__ == "__main__":
    unittest.main()
