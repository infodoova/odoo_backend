# doova_one_view/tests/test_report_job_resilience.py

import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "doova_one_view.settings")
django.setup()

import time
from pathlib import Path
from django.test import TransactionTestCase
from unittest.mock import patch, MagicMock
from asgiref.sync import async_to_sync
from django.utils import timezone
from odoo_app.models import Tenant, ReportSchedule, ReportLog
from doova_one_view.api.jobs.report_job import ReportJobManager


class TestReportJobResilience(TransactionTestCase):

    def setUp(self):
        self.tenant = Tenant.objects.create(name="Resilience Test Tenant")
        self.schedule = ReportSchedule.objects.create(
            tenant=self.tenant,
            report_type="executive",
            recipients=["user@example.com"],
            frequency="daily",
            next_send_at=timezone.now() - timezone.timedelta(minutes=5),
            consecutive_failures=0,
        )

    @patch("doova_one_view.api.jobs.report_job.ReportJobManager._build_analysis")
    @patch("django.conf.settings.EMAIL_HOST_USER", "smtp@example.com")
    def test_circuit_breaker_auto_disables_after_3_failures(self, mock_build):
        mock_build.side_effect = Exception("LLM Provider Timeout")
        self.schedule.consecutive_failures = 2
        self.schedule.save()

        now = timezone.now()
        async_to_sync(ReportJobManager._fire_schedule)(self.schedule, now)

        self.schedule.refresh_from_db()
        self.assertFalse(self.schedule.is_enabled)
        self.assertEqual(self.schedule.consecutive_failures, 3)
        self.assertIn("Auto-disabled after 3 consecutive failures", self.schedule.paused_reason)
        self.assertIn("LLM Provider Timeout", self.schedule.last_error)

        log = ReportLog.objects.filter(schedule=self.schedule).latest("sent_at")
        self.assertEqual(log.status, "failed")
        self.assertEqual(log.error_category, "ai_failure")
        self.assertIsNotNone(log.duration_seconds)

    @patch("doova_one_view.api.email.service.EmailService.send_report_email")
    @patch("doova_one_view.api.agent.tools_refactored.reporting_v2.generate_report_tool")
    @patch("doova_one_view.api.jobs.report_job.ReportJobManager._build_analysis")


    @patch("django.conf.settings.EMAIL_HOST_USER", "smtp@example.com")
    def test_success_resets_circuit_breaker_counters(self, mock_build, mock_gen, mock_email):
        mock_build.return_value = "## Test Report"
        mock_gen.return_value = {"filename": "test_report.pdf"}
        mock_email.return_value = {"status": "sent"}

        # Create a mock PDF file in reports dir
        from django.conf import settings
        reports_dir = Path(getattr(settings, "REPORTS_DIR", Path("reports")))
        reports_dir.mkdir(parents=True, exist_ok=True)
        pdf_file = reports_dir / "test_report.pdf"
        pdf_file.write_bytes(b"%PDF-1.4 Mock PDF Content")

        self.schedule.consecutive_failures = 2
        self.schedule.last_error = "Previous transient error"
        self.schedule.paused_reason = "Was warning"
        self.schedule.save()

        now = timezone.now()
        try:
            async_to_sync(ReportJobManager._fire_schedule)(self.schedule, now)

            self.schedule.refresh_from_db()
            self.assertTrue(self.schedule.is_enabled)
            self.assertEqual(self.schedule.consecutive_failures, 0)
            self.assertIsNone(self.schedule.last_error)
            self.assertIsNone(self.schedule.paused_reason)

            log = ReportLog.objects.filter(schedule=self.schedule).latest("sent_at")
            self.assertEqual(log.status, "sent")
            self.assertEqual(log.filename, "test_report.pdf")
            self.assertIsNotNone(log.duration_seconds)
            self.assertEqual(log.pdf_size_bytes, len(b"%PDF-1.4 Mock PDF Content"))
        finally:
            if pdf_file.exists():
                pdf_file.unlink()

    @patch("django.conf.settings.EMAIL_HOST_USER", "")
    def test_missing_smtp_credentials_trips_early_failure(self):
        now = timezone.now()
        async_to_sync(ReportJobManager._fire_schedule)(self.schedule, now)

        self.schedule.refresh_from_db()
        self.assertEqual(self.schedule.consecutive_failures, 1)

        log = ReportLog.objects.filter(schedule=self.schedule).latest("sent_at")
        self.assertEqual(log.status, "failed")
        self.assertEqual(log.error_category, "smtp_missing")
        self.assertEqual(log.error_message, "SMTP credentials not configured")


if __name__ == "__main__":
    import unittest
    unittest.main()
