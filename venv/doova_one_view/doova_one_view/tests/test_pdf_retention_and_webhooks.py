# doova_one_view/tests/test_pdf_retention_and_webhooks.py

import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "doova_one_view.settings")
django.setup()

import time
import shutil
from django.test import TestCase
from pathlib import Path
from unittest.mock import patch, MagicMock
from asgiref.sync import async_to_sync
from doova_one_view.api.jobs.report_job import cleanup_old_reports
from doova_one_view.api.jobs.alert_job import _send_webhook_notification


class TestPdfRetentionAndWebhooks(TestCase):

    def setUp(self):
        self.test_dir = Path("test_reports_temp")
        self.test_dir.mkdir(exist_ok=True)

    def tearDown(self):
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir)

    def test_pdf_retention_cleanup(self):
        # Create a fresh file (1 day old)
        fresh_file = self.test_dir / "fresh_report.pdf"
        fresh_file.write_text("fresh pdf content")

        # Create an old file (95 days old)
        old_file = self.test_dir / "old_report.pdf"
        old_file.write_text("old pdf content")
        old_mtime = time.time() - (95 * 86400)
        os.utime(old_file, (old_mtime, old_mtime))

        deleted = cleanup_old_reports(retention_days=90, reports_dir=str(self.test_dir))
        self.assertEqual(deleted, 1)
        self.assertTrue(fresh_file.exists())
        self.assertFalse(old_file.exists())

    @patch("httpx.AsyncClient.post")
    def test_send_webhook_notification(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_post.return_value = mock_resp

        async_to_sync(_send_webhook_notification)(
            webhook_url="https://hooks.slack.com/services/test/webhook",
            title="ALERT: Cash Drop Detected",
            summary="Cash balance dropped 25%",
            is_anomaly=True,
        )

        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args.kwargs
        self.assertIn("json", call_kwargs)
        self.assertIn("🚨 *ALERT: Cash Drop Detected*", call_kwargs["json"]["text"])


if __name__ == "__main__":
    unittest.main()
