"""
doova_one_view/api/agent/thresholds.py

Dynamic threshold resolver for tenant-specific financial configurations.
Reads warning, critical, 3-way matching tolerance, and data completeness settings.
"""

from typing import Dict, Any, Optional
from decimal import Decimal
import logging

logger = logging.getLogger(__name__)

DEFAULT_THRESHOLDS = {
    "variance_warning_threshold_pct": 2.0,
    "variance_critical_threshold_pct": 10.0,
    "po_matching_tolerance_pct": 1.0,
    "min_completeness_threshold_pct": 90.0,
}


def get_tenant_thresholds(tenant_ids: Optional[Any] = None) -> Dict[str, float]:
    """
    Retrieve configured thresholds for a specific tenant, falling back to enterprise defaults.
    """
    from doova_one_view.api.agent.query_context import normalize_tenant_ids
    t_ids = normalize_tenant_ids(tenant_ids)
    if not t_ids:
        return DEFAULT_THRESHOLDS.copy()

    tenant_id = t_ids[0]
    try:
        from odoo_app.models.tenant_financial_mapping import TenantFinancialMapping
        mapping = TenantFinancialMapping.objects.filter(tenant_id=tenant_id).first()
        if mapping:
            return {
                "variance_warning_threshold_pct": float(getattr(mapping, "variance_warning_threshold_pct", 2.0) or 2.0),
                "variance_critical_threshold_pct": float(getattr(mapping, "variance_critical_threshold_pct", 10.0) or 10.0),
                "po_matching_tolerance_pct": float(getattr(mapping, "po_matching_tolerance_pct", 1.0) or 1.0),
                "min_completeness_threshold_pct": float(getattr(mapping, "min_completeness_threshold_pct", 90.0) or 90.0),
            }
    except Exception as e:
        logger.debug(f"Failed to fetch custom thresholds for tenant {tenant_id}: {e}")

    return DEFAULT_THRESHOLDS.copy()
