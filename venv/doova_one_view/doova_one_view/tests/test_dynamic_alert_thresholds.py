# doova_one_view/tests/test_dynamic_alert_thresholds.py

import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "doova_one_view.settings")
django.setup()

from django.test import TestCase
from unittest.mock import patch
from doova_one_view.api.jobs.alert_prechecks import (
    resolve_effective_thresholds,
    check_cash_drop,
    check_low_inventory,
    BUSINESS_MODEL_BASELINES,
)


class TestDynamicAlertThresholds(TestCase):

    @patch("doova_one_view.api.agent.tools_refactored.common.get_tenant_profile_tool")
    def test_business_model_profile_resolution(self, mock_profile):
        # Service business profile
        mock_profile.return_value = {"business_type": "Service", "currency": "USD"}
        eff_service = resolve_effective_thresholds("service-tenant-1")
        self.assertEqual(eff_service["cash_drop_pct"], 35.0)
        self.assertEqual(eff_service["ar_overdue_ratio"], 0.40)
        self.assertEqual(eff_service["low_stock_threshold"], 0.0)

        # Product business profile
        mock_profile.return_value = {"business_type": "Product", "currency": "USD"}
        eff_product = resolve_effective_thresholds("product-tenant-1")
        self.assertEqual(eff_product["cash_drop_pct"], 12.0)
        self.assertEqual(eff_product["low_stock_threshold"], 15.0)

    def test_custom_schedule_threshold_overrides(self):
        custom = {
            "cash_drop_pct": 10.0,
            "ar_overdue_ratio": 0.20,
            "low_stock_threshold": 25,
        }
        eff = resolve_effective_thresholds("any-tenant", custom_thresholds=custom)
        self.assertEqual(eff["cash_drop_pct"], 10.0)
        self.assertEqual(eff["ar_overdue_ratio"], 0.20)
        self.assertEqual(eff["low_stock_threshold"], 25.0)

    @patch("doova_one_view.api.jobs.alert_prechecks.run_query")
    def test_check_cash_drop_custom_threshold(self, mock_query):
        # Recent cash dropped 15% (recent = 85, avg = 100)
        mock_query.return_value = [{"recent_cash": 85.0, "avg_cash_7d": 100.0}]

        # Standard threshold 20% -> NOT triggered (15% drop < 20%)
        triggered, _ = check_cash_drop("tenant-1", thresholds={"cash_drop_pct": 20.0})
        self.assertFalse(triggered)

        # Custom threshold 10% -> TRIGGERED (15% drop > 10%)
        triggered, msg = check_cash_drop("tenant-1", thresholds={"cash_drop_pct": 10.0})
        self.assertTrue(triggered)
        self.assertIn("dropped by 15.0%", msg)

    @patch("doova_one_view.api.agent.tools_refactored.common.get_tenant_profile_tool")
    @patch("doova_one_view.api.jobs.alert_prechecks.run_query")
    def test_service_company_ignores_inventory(self, mock_query, mock_profile):
        mock_profile.return_value = {"business_type": "Service", "currency": "USD"}
        # Inventory check for service business should return False without running query
        triggered, _ = check_low_inventory("service-tenant")
        self.assertFalse(triggered)
        mock_query.assert_not_called()


if __name__ == "__main__":
    unittest.main()
