# doova_one_view/tests/test_metrics_observability.py

import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "doova_one_view.settings")
django.setup()

import json
import logging
from django.test import TestCase
from doova_one_view.api.agent.metrics import metrics_registry, JSONLogFormatter


class TestMetricsObservability(TestCase):

    def setUp(self):
        # Reset counters before test
        metrics_registry._init_counters()

    def test_metrics_registry_recording(self):
        metrics_registry.record_alert_check(condition_triggered=True, alert_sent=True, skipped_llm=False)
        metrics_registry.record_alert_check(condition_triggered=False, alert_sent=False, skipped_llm=True)
        metrics_registry.record_report_job(status="sent")
        metrics_registry.record_rate_limit_block()

        summary = metrics_registry.get_ops_summary()
        self.assertEqual(summary["status"], "healthy")
        self.assertEqual(summary["metrics"]["alerts_triggered_total"], 2)
        self.assertEqual(summary["metrics"]["alerts_sent_total"], 1)
        self.assertEqual(summary["metrics"]["prechecks_skipped_llm_total"], 1)
        self.assertEqual(summary["metrics"]["reports_sent_total"], 1)
        self.assertEqual(summary["metrics"]["rate_limit_blocks_total"], 1)
        self.assertEqual(summary["estimated_llm_cost_saved_usd"], 0.15)

    def test_prometheus_exposition_format(self):
        metrics_registry.record_alert_check(condition_triggered=False, alert_sent=False, skipped_llm=True)
        prom_text = metrics_registry.get_prometheus_metrics()
        self.assertIn("# HELP nexus_alerts_triggered_total", prom_text)
        self.assertIn("# TYPE nexus_alerts_triggered_total counter", prom_text)
        self.assertIn("nexus_prechecks_skipped_llm_total 1", prom_text)

    def test_json_log_formatter(self):
        formatter = JSONLogFormatter()
        logger = logging.getLogger("test.json")
        record = logger.makeRecord(
            name="test.json",
            level=logging.INFO,
            fn="test_file.py",
            lno=10,
            msg="Alert dispatched successfully",
            args=(),
            exc_info=None,
        )
        record.tenant_id = "test-tenant-123"
        record.event_type = "alert_dispatched"

        formatted = formatter.format(record)
        data = json.loads(formatted)
        self.assertEqual(data["level"], "INFO")
        self.assertEqual(data["message"], "Alert dispatched successfully")
        self.assertEqual(data["tenant_id"], "test-tenant-123")
        self.assertEqual(data["event_type"], "alert_dispatched")


if __name__ == "__main__":
    unittest.main()
