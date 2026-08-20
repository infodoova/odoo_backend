"""
doova_one_view/api/agent/completeness.py

Data Completeness & Confidence Evaluator.
Measures data integrity, database sync health, and tool query success ratios.
Triggers auto-pause gates when completeness drops below threshold to prevent degraded client reports.
"""

from typing import Dict, List, Any, Optional, Tuple
import logging

logger = logging.getLogger(__name__)

STANDARD_EXECUTIVE_TOOLS = [
    "calculate_pnl",
    "get_balance_sheet",
    "get_receivables_analysis",
    "get_payables_analysis",
    "get_sales_summary",
    "get_working_capital",
]

DIAGNOSTIC_AUDIT_TOOLS = [
    "audit_invoice_po_matching",
    "get_receivables_analysis",
]


class CompletenessEvaluator:
    """
    Evaluates execution success ratios and database completeness for automated reporting jobs.
    """

    @classmethod
    def evaluate(
        cls,
        successful_tools: List[str],
        failed_tools: Optional[List[str]] = None,
        expected_tools: Optional[List[str]] = None,
        min_threshold_pct: float = 90.0,
    ) -> Dict[str, Any]:
        failed = failed_tools or []
        expected = expected_tools or STANDARD_EXECUTIVE_TOOLS
        
        # Calculate unique planned tools
        all_planned = list(set(expected + successful_tools + failed))
        total_count = len(all_planned) if all_planned else 1
        
        # Count successful required tools
        success_set = set(successful_tools)
        successful_count = len(success_set)
        
        completeness_pct = round((successful_count / total_count) * 100.0, 1)
        passed = completeness_pct >= min_threshold_pct
        
        missing_critical = [t for t in expected if t not in success_set]

        return {
            "score": completeness_pct,
            "passed": passed,
            "min_threshold_pct": min_threshold_pct,
            "successful_tools": list(success_set),
            "failed_tools": failed,
            "missing_critical": missing_critical,
            "incident_description": (
                f"Data completeness degraded to {completeness_pct}% (minimum required: {min_threshold_pct}%). "
                f"Missing/failed tools: {', '.join(failed or missing_critical)}"
                if not passed else "Data completeness verified."
            )
        }
