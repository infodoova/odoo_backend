# Nexus Proactive Alert Intelligence

The Alerting API manages scheduled proactive monitoring, anomaly detection jobs, instant check dispatches, and alert execution logs for Doova One View.

For the complete architectural and operational breakdown, see the **[Nexus AI Alerting System — Technical Deep Dive](file:///c:/Users/PC/Desktop/doova_one_view/odoo_backend/ALERTING_SYSTEM_DEEP_DIVE.md)**.

## 📁 Endpoints & Capabilities

- **`POST /api/v1/alerts/schedules`**: Create a scheduled alert with custom thresholds, recipients, and company filters.
- **`GET /api/v1/alerts/schedules`**: List all schedules configured for the tenant.
- **`POST /api/v1/alerts/schedules/{id}/run`**: Trigger an on-demand instant check (governed by a 60s cooldown).
- **`GET /api/v1/alerts/logs`**: Query alert execution history, anomaly summaries, and dispatch statuses.

## ⚙️ Core Components

- **`routes.py`**: FastAPI routing and authentication integration.
- **`schemas.py`**: Pydantic schemas for schedule management, context serialization (`AlertContextPayload`), and LLM response parsing (`LlmAlertResult`).
- **`alert_job.py`**: Background cron worker, concurrency throttles, rate limiters, and LangChain AI agent invocation.
- **`alert_prechecks.py`**: 8 deterministic SQL pre-checks and 3-tier dynamic threshold resolution (`resolve_effective_thresholds`).
