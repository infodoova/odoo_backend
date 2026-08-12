# doova_one_view/api/agent/metrics.py

import time
import json
import logging
from threading import Lock
from typing import Dict, Any

logger = logging.getLogger("doova.agent.metrics")


class JSONLogFormatter(logging.Formatter):
    """Structured JSON formatter for log aggregation (Datadog, ELK, Grafana Loki, CloudWatch)."""

    def format(self, record: logging.LogRecord) -> str:
        log_obj: Dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%SZ"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if hasattr(record, "tenant_id"):
            log_obj["tenant_id"] = getattr(record, "tenant_id")
        if hasattr(record, "event_type"):
            log_obj["event_type"] = getattr(record, "event_type")
        if hasattr(record, "duration_ms"):
            log_obj["duration_ms"] = getattr(record, "duration_ms")
        if record.exc_info:
            log_obj["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_obj)


class AgentMetricsRegistry:
    """
    Thread-safe in-process metrics collector exposing Prometheus & JSON ops visibility.
    """

    _instance = None
    _lock = Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(AgentMetricsRegistry, cls).__new__(cls)
                cls._instance._init_counters()
            return cls._instance

    def _init_counters(self):
        self._mutex = Lock()
        self.metrics = {
            "alerts_triggered_total": 0,
            "alerts_sent_total": 0,
            "alerts_failed_total": 0,
            "prechecks_skipped_llm_total": 0,
            "reports_generated_total": 0,
            "reports_sent_total": 0,
            "reports_failed_total": 0,
            "rate_limit_blocks_total": 0,
            "llm_calls_total": 0,
        }

    def increment(self, metric_name: str, amount: int = 1):
        with self._mutex:
            if metric_name in self.metrics:
                self.metrics[metric_name] += amount

    def record_alert_check(self, condition_triggered: bool = False, alert_sent: bool = False, skipped_llm: bool = False, status: str = "completed"):
        with self._mutex:
            self.metrics["alerts_triggered_total"] += 1
            if skipped_llm:
                self.metrics["prechecks_skipped_llm_total"] += 1
            else:
                self.metrics["llm_calls_total"] += 1

            if alert_sent:
                self.metrics["alerts_sent_total"] += 1

            if status == "failed":
                self.metrics["alerts_failed_total"] += 1

    def record_report_job(self, status: str = "sent"):
        with self._mutex:
            self.metrics["reports_generated_total"] += 1
            self.metrics["llm_calls_total"] += 1
            if status == "sent":
                self.metrics["reports_sent_total"] += 1
            else:
                self.metrics["reports_failed_total"] += 1

    def record_rate_limit_block(self):
        with self._mutex:
            self.metrics["rate_limit_blocks_total"] += 1

    def get_ops_summary(self) -> Dict[str, Any]:
        with self._mutex:
            # Estimate LLM cost saved by Tier 1 prechecks ($0.15 per skipped check baseline)
            skipped = self.metrics["prechecks_skipped_llm_total"]
            cost_saved_usd = round(skipped * 0.15, 2)
            return {
                "status": "healthy",
                "metrics": dict(self.metrics),
                "estimated_llm_cost_saved_usd": cost_saved_usd,
                "uptime_timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }

    def get_prometheus_metrics(self) -> str:
        with self._mutex:
            lines = [
                "# HELP nexus_alerts_triggered_total Total alert checks executed",
                "# TYPE nexus_alerts_triggered_total counter",
                f"nexus_alerts_triggered_total {self.metrics['alerts_triggered_total']}",
                "",
                "# HELP nexus_alerts_sent_total Total alert emails successfully dispatched",
                "# TYPE nexus_alerts_sent_total counter",
                f"nexus_alerts_sent_total {self.metrics['alerts_sent_total']}",
                "",
                "# HELP nexus_alerts_failed_total Total alert check failures",
                "# TYPE nexus_alerts_failed_total counter",
                f"nexus_alerts_failed_total {self.metrics['alerts_failed_total']}",
                "",
                "# HELP nexus_prechecks_skipped_llm_total Total Tier 1 prechecks that skipped LLM inference",
                "# TYPE nexus_prechecks_skipped_llm_total counter",
                f"nexus_prechecks_skipped_llm_total {self.metrics['prechecks_skipped_llm_total']}",
                "",
                "# HELP nexus_reports_generated_total Total AI reports generated",
                "# TYPE nexus_reports_generated_total counter",
                f"nexus_reports_generated_total {self.metrics['reports_generated_total']}",
                "",
                "# HELP nexus_reports_sent_total Total report emails sent",
                "# TYPE nexus_reports_sent_total counter",
                f"nexus_reports_sent_total {self.metrics['reports_sent_total']}",
                "",
                "# HELP nexus_rate_limit_blocks_total Total requests blocked by rate limiter",
                "# TYPE nexus_rate_limit_blocks_total counter",
                f"nexus_rate_limit_blocks_total {self.metrics['rate_limit_blocks_total']}",
                "",
            ]
            return "\n".join(lines)


metrics_registry = AgentMetricsRegistry()
