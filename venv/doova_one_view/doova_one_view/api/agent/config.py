"""
AI Agent configuration.

Reads secrets from environment / Django settings.
All Claude model identifiers and token budgets live here.
"""

import os
from django.conf import settings as django_settings


class AgentConfig:
    """Centralised knobs for the AI financial-advisor agent."""

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
    FAST_MODEL = "claude-sonnet-4-6"
    REASONING_MODEL = "claude-opus-4-8"
    SUMMARIZER_MODEL = "claude-haiku-4-5-20251001"
    SQL_AGENT_MODEL = "claude-haiku-4-5-20251001"

    # ── Token budgets ─────────────────────────────────────────────────
    # 8192 supports the CFO INTERNAL THOUGHT PROCESS + STRATEGIC RECOMMENDATION
    # sections without truncation on compound multi-tool analyses.
    MAX_FAST_TOKENS = 4096
    MAX_REASONING_TOKENS = 8000
    MAX_ROUTER_TOKENS = 20
    # 1024 ensures the summarizer captures exact KPI numbers and date ranges
    # without truncating mid-way through a financial summary.
    MAX_SUMMARIZER_TOKENS = 1024

    # ── Memory ────────────────────────────────────────────────────────
    SUMMARIZE_EVERY_N = 4

    # ── Business thresholds ───────────────────────────────────────────
    LOW_MARGIN_THRESHOLD = 15.0
    HIGH_RECEIVABLES_DAYS = 60
    LOW_STOCK_THRESHOLD = 10
    EXPIRY_WARNING_DAYS = 30
    
    # ── URL Configuration ─────────────────────────────────────────────
    PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")
    API_BASE_URL = os.getenv("API_BASE_URL", f"{PUBLIC_BASE_URL}/api/v1")
