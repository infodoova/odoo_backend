# doova_one_view/tests/test_concurrent_job_execution.py

import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "doova_one_view.settings")
django.setup()

import asyncio
from django.test import TransactionTestCase
from unittest.mock import patch, MagicMock
from asgiref.sync import async_to_sync
from django.utils import timezone
from odoo_app.models import Tenant, ReportSchedule, AlertSchedule
from doova_one_view.api.jobs.report_job import ReportJobManager
from doova_one_view.api.jobs.alert_job import AlertJobManager


class TestConcurrentJobExecution(TransactionTestCase):

    def setUp(self):
        self.tenant = Tenant.objects.create(name="Concurrent Execution Test Tenant")

    @patch("doova_one_view.api.jobs.report_job.ReportJobManager._fire_schedule")
    def test_report_job_processes_schedules_concurrently(self, mock_fire):
        # Create 3 due report schedules
        for i in range(3):
            ReportSchedule.objects.create(
                tenant=self.tenant,
                report_type="executive",
                recipients=[f"user{i}@example.com"],
                frequency="daily",
                next_send_at=timezone.now() - timezone.timedelta(minutes=5),
            )

        async_to_sync(ReportJobManager._process_due_schedules)()
        self.assertEqual(mock_fire.call_count, 3)

    @patch("doova_one_view.api.jobs.alert_job.AlertJobManager.run_check")
    def test_alert_job_processes_schedules_concurrently(self, mock_check):
        mock_check.return_value = {"condition_triggered": False, "summary": "OK", "alert_sent": False, "log_id": 1}

        # Create 3 due alert schedules
        for i in range(3):
            AlertSchedule.objects.create(
                tenant=self.tenant,
                name=f"Alert Monitor {i}",
                recipients=[f"user{i}@example.com"],
                next_check_at=timezone.now() - timezone.timedelta(minutes=5),
            )

        async_to_sync(AlertJobManager._process_due_schedules)()
        self.assertEqual(mock_check.call_count, 3)


if __name__ == "__main__":
    unittest.main()
