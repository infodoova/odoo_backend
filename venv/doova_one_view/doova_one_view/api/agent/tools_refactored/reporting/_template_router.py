# doova_one_view/api/agent/tools_refactored/reporting/_template_router.py

from pathlib import Path
from typing import Optional, Tuple, Dict, Any

from ..template_registry import TEMPLATE_REGISTRY


def _get_reports_dir() -> Path:
    from django.conf import settings
    reports_dir = Path(getattr(settings, "REPORTS_DIR", Path("reports")))
    reports_dir.mkdir(parents=True, exist_ok=True)
    return reports_dir


def _resolve_report_template(report_type: str | None = None, prompt_text: str = "") -> tuple[str, str, dict]:
    """
    Selects the Jinja2 template file and returns (template_filename, canonical_key, metadata).
    Delegates to ReportTypeClassifier (beside RouterNode) with 100% backward compatibility.
    """
    if not report_type and not prompt_text:
        return "report_template.html", "health", TEMPLATE_REGISTRY.get("health", {})

    from doova_one_view.api.agent.report_classifier import ReportTypeClassifier
    canonical_key = ReportTypeClassifier.classify(prompt=prompt_text, raw_type=report_type)

    if canonical_key in TEMPLATE_REGISTRY:
        meta = TEMPLATE_REGISTRY[canonical_key]
        return meta["template_file"], canonical_key, meta

    return "report_template.html", "health", TEMPLATE_REGISTRY.get("health", {})
