# doova_one_view/tests/test_alert_rate_limiting.py

import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "doova_one_view.settings")
django.setup()

from django.test import TestCase
from datetime import timedelta
from django.utils import timezone
from unittest.mock import patch, MagicMock
from asgiref.sync import async_to_sync
from odoo_app.models import Tenant, AlertSchedule, AlertLog
from doova_one_view.api.jobs.alert_job import AlertJobManager
from doova_one_view.api.agent.config import AgentConfig
from fastapi import HTTPException


class TestAlertRateLimiting(TestCase):

    def setUp(self):
        self.tenant = Tenant.objects.create(name="Rate Limit Test Tenant")
        self.schedule = AlertSchedule.objects.create(
            tenant=self.tenant,
            name="Daily Financial Risk Alert",
            recipients=["cfo@example.com"],
            next_check_at=timezone.now(),
        )

    def test_daily_rate_limit_not_exceeded(self):
        # 5 logs in last 24h (under limit of 20)
        for _ in range(5):
            AlertLog.objects.create(
                schedule=self.schedule,
                tenant=self.tenant,
                status="completed",
                condition_triggered=False,
            )

        exceeded = async_to_sync(AlertJobManager._check_daily_rate_limit)(str(self.tenant.id))
        self.assertFalse(exceeded)

    def test_daily_rate_limit_exceeded(self):
        # Create 30 logs in last 24h (reaching max daily threshold)
        for _ in range(30):
            AlertLog.objects.create(
                schedule=self.schedule,
                tenant=self.tenant,
                status="completed",
                condition_triggered=False,
            )

        exceeded = async_to_sync(AlertJobManager._check_daily_rate_limit)(str(self.tenant.id))
        self.assertTrue(exceeded)

    @patch("doova_one_view.api.jobs.alert_job.AlertJobManager._detect_anomalies")
    def test_run_check_blocks_when_daily_limit_exceeded(self, mock_detect):
        # Fill tenant logs up to the limit of 30
        for _ in range(30):
            AlertLog.objects.create(
                schedule=self.schedule,
                tenant=self.tenant,
                status="completed",
                condition_triggered=False,
            )

        # Instant run-now should raise HTTP 429
        with self.assertRaises(HTTPException) as ctx:
            async_to_sync(AlertJobManager.run_check)(
                schedule=self.schedule,
                tenant_id=str(self.tenant.id),
                send_email=False,
                is_instant=True,
            )
        self.assertEqual(ctx.exception.status_code, 429)
        detail_text = ctx.exception.detail["message"] if isinstance(ctx.exception.detail, dict) else str(ctx.exception.detail)
        self.assertIn("Maximum daily AI alert checks", detail_text)
        mock_detect.assert_not_called()


        # Scheduled background loop should gracefully skip AI inference
        res = async_to_sync(AlertJobManager.run_check)(
            schedule=self.schedule,
            tenant_id=str(self.tenant.id),
            send_email=False,
            is_instant=False,
        )
        self.assertFalse(res["condition_triggered"])
        self.assertIn("RATE LIMIT", res["summary"])
        mock_detect.assert_not_called()


if __name__ == "__main__":
    unittest.main()
