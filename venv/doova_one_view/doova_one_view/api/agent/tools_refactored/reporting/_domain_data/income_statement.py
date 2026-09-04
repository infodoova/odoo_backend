# doova_one_view/api/agent/tools_refactored/reporting/_domain_data/income_statement.py

from typing import Optional, List, Dict, Any


def enrich(
    data: dict,
    pnl_ctx: dict,
    tenant_id: str,
    resolved_company_ids: list[int] | None,
    start_date: str,
    end_date: str,
    base_currency: str | None,
    tenant_ids: list[str] | None,
    currency: str,
    prior_start: str | None = None,
    prior_end: str | None = None,
    comparison_label: str = "",
    **kwargs
) -> None:
    """Enriches data dict for Income Statement domain. Shared pnl_statement table is generated in _base."""
    # The pnl_statement table and variance badges are populated by _base.py.
    # This module is reserved for any additional income-statement-specific sub-schedules.
    pass
