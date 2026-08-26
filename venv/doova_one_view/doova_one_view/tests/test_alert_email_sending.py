# doova_one_view/tests/test_alert_email_sending.py

import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "doova_one_view.settings")
django.setup()

from django.test import TestCase
from django.utils import timezone
from unittest.mock import patch, AsyncMock
from asgiref.sync import async_to_sync
from odoo_app.models import Tenant, AlertSchedule, AlertLog
from doova_one_view.api.jobs.alert_job import AlertJobManager


class TestAlertEmailSending(TestCase):

    def setUp(self):
        self.tenant = Tenant.objects.create(name="Email Alert Test Tenant")
        self.schedule = AlertSchedule.objects.create(
            tenant=self.tenant,
            name="Daily Executive Anomaly Alert",
            prompt="Are there any critical financial anomalies or overdue risks I should know about today?",
            recipients=["cfo@example.com", "finance@example.com"],
            next_check_at=timezone.now(),
        )

    @patch("doova_one_view.api.email.service.EmailService.send")
    @patch("doova_one_view.api.jobs.alert_job.AlertJobManager._detect_anomalies")
    def test_run_check_sends_email_when_anomaly_triggered(self, mock_detect, mock_email_send):
        # Setup mocks: AI engine detects critical AR risk
        mock_detect.return_value = (
            "CRITICAL: 100% of AR (XAF 480.8M) is overdue, concentrated in two customers.",
            True,
            "critical"
        )
        mock_email_send.return_value = {"status": "sent", "attempts": 1}

        # Run alert check with send_email=True
        result = async_to_sync(AlertJobManager.run_check)(
            schedule=self.schedule,
            tenant_id=str(self.tenant.id),
            send_email=True,
            is_instant=True,
        )

        # Assertions
        self.assertTrue(result["condition_triggered"])
        self.assertTrue(result["alert_sent"])
        self.assertIsNotNone(result["log_id"])

        # Check DB AlertLog record
        log = AlertLog.objects.get(id=result["log_id"])
        self.assertEqual(log.status, "completed")
        self.assertTrue(log.condition_triggered)
        self.assertTrue(log.alert_sent)
        self.assertIn("100% of AR", log.summary)

        # Verify EmailService.send was invoked for both recipients
        self.assertEqual(mock_email_send.call_count, 2)
        called_recipients = [call.kwargs["to"] for call in mock_email_send.call_args_list]
        self.assertIn("cfo@example.com", called_recipients)
        self.assertIn("finance@example.com", called_recipients)

        # Check email subject prefix
        subject = mock_email_send.call_args_list[0].kwargs["subject"]
        self.assertIn("CRITICAL ALERT", subject)

    @patch("doova_one_view.api.email.service.EmailService.send")
    @patch("doova_one_view.api.jobs.alert_job.AlertJobManager._detect_anomalies")
    def test_run_check_skips_email_when_all_clear(self, mock_detect, mock_email_send):
        # Setup mocks: AI engine finds no anomalies
        mock_detect.return_value = (
            "OK: All monitored financial metrics are within normal baseline ranges.",
            False,
            "success"
        )

        # Run scheduled check
        result = async_to_sync(AlertJobManager.run_check)(
            schedule=self.schedule,
            tenant_id=str(self.tenant.id),
            send_email=True,
            is_instant=False,
        )

        # Assertions: No email dispatched when clear in background loop
        self.assertFalse(result["condition_triggered"])
        self.assertFalse(result["alert_sent"])
        mock_email_send.assert_not_called()


if __name__ == "__main__":
    import unittest
    unittest.main()
