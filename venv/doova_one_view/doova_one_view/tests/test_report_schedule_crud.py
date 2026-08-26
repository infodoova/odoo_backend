# doova_one_view/tests/test_report_schedule_crud.py

import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "doova_one_view.settings")
django.setup()

from datetime import datetime, timezone
from django.test import TestCase
from pydantic import ValidationError
from doova_one_view.api.reports.schemas import ReportScheduleCreate, ReportScheduleUpdate


class TestReportScheduleValidation(TestCase):

    def test_valid_timezone_accepted(self):
        payload = ReportScheduleCreate(
            recipients=["user@example.com"],
            frequency="daily",
            timezone="Asia/Riyadh",
            start_at=datetime.now(timezone.utc),
        )
        self.assertEqual(payload.timezone, "Asia/Riyadh")

    def test_invalid_timezone_rejected(self):
        with self.assertRaises(ValidationError) as ctx:
            ReportScheduleCreate(
                recipients=["user@example.com"],
                frequency="daily",
                timezone="Invalid/NonExistent_TZ",
                start_at=datetime.now(timezone.utc),
            )
        self.assertIn("Invalid timezone", str(ctx.exception))

    def test_update_schema_timezone_validation(self):
        with self.assertRaises(ValidationError):
            ReportScheduleUpdate(timezone="Fake/Zone")

        valid_update = ReportScheduleUpdate(timezone="Europe/London")
        self.assertEqual(valid_update.timezone, "Europe/London")


if __name__ == "__main__":
    import unittest
    unittest.main()
