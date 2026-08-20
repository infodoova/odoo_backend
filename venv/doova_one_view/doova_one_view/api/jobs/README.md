# Jobs Module

Manages background tasks and scheduled processes, such as data synchronization with Odoo and proactive AI anomaly alert monitoring.

For the full technical deep dive on alerting, see **[Nexus AI Alerting System — Technical Deep Dive](file:///c:/Users/PC/Desktop/doova_one_view/odoo_backend/ALERTING_SYSTEM_DEEP_DIVE.md)**.

## 📁 Structure

- **`alert_job.py`**: Background cron loop manager (`AlertJobManager`) that processes due alert schedules, enforces rate limits and concurrency throttles, calls Tier 1 pre-checks and Tier 2 LLM agents, and dispatches HTML executive emails.
- **`alert_prechecks.py`**: Deterministic SQL pre-checks (cash drop, overdue AR, revenue cliff, duplicate invoices, low stock, transaction outliers, unbalanced journals, weekend postings) and dynamic threshold resolution (`resolve_effective_thresholds`).
- **`sync_job.py`**: Implementation of the Odoo data synchronization task.

## ⚙️ Key Features

- **Proactive AI Monitoring**: Hourly evaluation of financial and operational anomalies per tenant.
- **Cost-Optimized Two-Tier Architecture**: Skips expensive LLM calls when deterministic SQL pre-checks pass.
- **Multi-Tenant Rate Limiting & Claim Locking**: Prevents duplicate checks and protects API limits.
- **Manual & Scheduled Syncs**: Handling long-running data processing tasks outside the main request cycle.
