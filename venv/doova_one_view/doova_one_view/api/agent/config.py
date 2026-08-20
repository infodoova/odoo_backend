"""
AI Agent configuration.

Reads secrets from environment / Django settings.
All Claude model identifiers and token budgets live here.
"""

import os
from django.conf import settings as django_settings


class AgentConfig:
    """Centralised knobs for the AI business advisor agent."""

    # ── LLM provider ──────────────────────────────────────────────────
    ANTHROPIC_API_KEY: str = (
        getattr(django_settings, "ANTHROPIC_API_KEY", None)
        or os.getenv("ANTHROPIC_API_KEY", "")
    )

    # Odoo Connection
    ODOO_URL = os.getenv("ODOO_URL") or getattr(django_settings, "ODOO_URL", "")
    ODOO_DB = os.getenv("ODOO_DB") or getattr(django_settings, "ODOO_DB", "")
    ODOO_USERNAME = os.getenv("ODOO_USERNAME") or getattr(django_settings, "ODOO_USERNAME", "")
    ODOO_API_KEY = os.getenv("ODOO_API_KEY") or getattr(django_settings, "ODOO_API_KEY", "")

    # ── Claude models ─────────────────────────────────────────────────
    ROUTER_MODEL = "claude-haiku-4-5-20251001"
    FAST_MODEL = "claude-sonnet-5"
    REASONING_MODEL = "claude-opus-5"
    SUMMARIZER_MODEL = "claude-haiku-4-5-20251001"
    SQL_AGENT_MODEL = "claude-haiku-4-5-20251001"

    # ── Extended Capabilities ─────────────────────────────────────────
    ENABLE_THINKING = True
    THINKING_BUDGET = 32000

    # ── Token budgets ─────────────────────────────────────────────────
    # 8192 supports the internal analysis + recommendations
    # sections without truncation on compound multi-tool analyses.
    # Use MAX_REPORT_TOKENS for report-generation endpoints that need longer output.
    MAX_FAST_TOKENS = 8192
    MAX_REPORT_TOKENS = 16384
    MAX_REASONING_TOKENS = 8000
    MAX_ROUTER_TOKENS = 20
    # 1024 ensures the summarizer captures exact KPI numbers and date ranges
    # without truncating mid-way through a financial summary.
    MAX_SUMMARIZER_TOKENS = 1024

    # ── Plan State ────────────────────────────────────────────────────
    # Pending plans expire after this many minutes of inactivity to prevent
    # stale plan re-execution on any subsequent message in the same session.
    PLAN_EXPIRY_MINUTES = 30

    # ── Memory ────────────────────────────────────────────────────────
    SUMMARIZE_EVERY_N = 4

    # ── SQL Agent ─────────────────────────────────────────────────────
    MAX_SQL_RETRIES = 3

    # ── Cache TTLs (seconds) ──────────────────────────────────────────
    CACHE_TTL_SCHEMA = 1800        # 30 min
    CACHE_TTL_TENANT_PROFILE = 900 # 15 min
    CACHE_TTL_FINANCIAL = 300      # 5 min
    CACHE_MAX_SIZE = 128           # Max entries per cache

    # ── Alert Pre-Check & Safety Thresholds ───────────────────────────
    ALERT_CASH_DROP_PCT = 20.0        # Trigger if cash drops > 20%
    ALERT_AR_OVERDUE_RATIO = 0.30     # Trigger if overdue > 30% of total AR
    ALERT_REVENUE_DEVIATION_PCT = 30.0 # Trigger if revenue deviates > 30% from daily avg
    ALERT_LOW_STOCK_THRESHOLD = 5      # Trigger if available qty < 5
    ALERT_LARGE_TXN_MULTIPLIER = 3.0   # Trigger if single txn > 3x avg

    # ── Alert Rate Limiting & Cooldowns ───────────────────────────────
    MAX_DAILY_ALERT_CHECKS_PER_TENANT = 30  # Max AI-driven alert checks per tenant per 24 hours
    RUN_NOW_COOLDOWN_SECONDS = 60           # Minimum seconds between instant run-now calls for a schedule

    # ── Business thresholds ───────────────────────────────────────────
    LOW_MARGIN_THRESHOLD = 15.0
    HIGH_RECEIVABLES_DAYS = 60
    LOW_STOCK_THRESHOLD = 10
    EXPIRY_WARNING_DAYS = 30
    
    # ── URL Configuration ─────────────────────────────────────────────
    PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
    API_BASE_URL = os.getenv("API_BASE_URL", f"{PUBLIC_BASE_URL}/api/v1" if PUBLIC_BASE_URL else "/api/v1")
