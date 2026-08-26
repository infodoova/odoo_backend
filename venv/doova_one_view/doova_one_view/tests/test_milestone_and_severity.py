# doova_one_view/tests/test_milestone_and_severity.py

import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "doova_one_view.settings")
django.setup()

from django.test import TestCase
from unittest.mock import patch
from doova_one_view.api.jobs.alert_prechecks import (
    check_revenue_anomaly,
    run_all_prechecks,
)


class TestMilestoneAndSeverity(TestCase):

    @patch("doova_one_view.api.jobs.alert_prechecks.run_query")
    def test_severe_revenue_drop_precheck(self, mock_query):
        # 24h revenue dropped from 10,000 to 2,000 (80% drop > 30% threshold)
        mock_query.return_value = [{"rev_24h": 2000.0, "avg_rev_30d": 10000.0}]

        res = check_revenue_anomaly("tenant-1")
        self.assertTrue(res[0])
        self.assertEqual(res[2], "warning")
        self.assertIn("Severe Revenue Drop detected", res[1])

    @patch("doova_one_view.api.jobs.alert_prechecks.check_unbalanced_journals")
    @patch("doova_one_view.api.jobs.alert_prechecks.check_revenue_anomaly")
    def test_run_all_prechecks_severe_problem_ranking(self, mock_rev, mock_unbalanced):
        mock_rev.return_value = (True, "Severe Revenue Drop detected", "warning")
        mock_unbalanced.return_value = (True, "Unbalanced journal found", "critical")

        res = run_all_prechecks("tenant-1")
        self.assertTrue(res["any_triggered"])
        self.assertEqual(res["highest_severity"], "critical")
        self.assertIn("revenue_anomaly", res["triggered_checks"])
        self.assertIn("unbalanced_journals", res["triggered_checks"])


if __name__ == "__main__":
    unittest.main()
