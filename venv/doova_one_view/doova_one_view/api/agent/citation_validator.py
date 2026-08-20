"""
doova_one_view/api/agent/citation_validator.py

Programmatic Citation Envelope & Anti-Hallucination Failure Gate.
Verifies LLM-emitted citations against deterministic tool execution stores.
If ungrounded claims are found, enables a 1-step structured repair retry and strictly
blocks unverified distribution if still invalid.
"""

import json
import re
import logging
from typing import Dict, List, Any, Optional, Tuple

logger = logging.getLogger(__name__)


class CitationValidator:
    """
    Validates structured numerical claims and record citations against verified database ground truth.
    """

    @staticmethod
    def extract_citations_from_text(text: str) -> List[Dict[str, Any]]:
        """
        Extracts structured citations from markdown/JSON blocks or XML tags (<citations>...</citations>).
        """
        citations = []
        if not text:
            return citations

        # 1. Search for <citations>[...]</citations>
        xml_match = re.search(r'<citations>\s*(\[.*?\])\s*</citations>', text, flags=re.DOTALL)
        if xml_match:
            try:
                parsed = json.loads(xml_match.group(1))
                if isinstance(parsed, list):
                    return parsed
            except Exception:
                pass

        # 2. Search for ```citations ... ``` or ```json with citation keys
        code_blocks = re.findall(r'```(?:citations|json)?\s*\n(.*?)\n```', text, flags=re.DOTALL)
        for block in code_blocks:
            try:
                parsed = json.loads(block)
                if isinstance(parsed, list) and all(isinstance(c, dict) for c in parsed):
                    if any("metric_key" in c or "record_id" in c or "value" in c for c in parsed):
                        return parsed
                elif isinstance(parsed, dict) and "citations" in parsed:
                    return parsed["citations"]
            except Exception:
                continue

        return citations

    @classmethod
    def validate_citations(
        cls,
        citations: List[Dict[str, Any]],
        ground_truth: Dict[str, Any],
        tolerance_pct: float = 1.0,
    ) -> Dict[str, Any]:
        """
        Validates each citation against verified ground truth metrics or record stores.
        """
        if not citations:
            return {
                "is_valid": True,
                "valid_count": 0,
                "invalid_count": 0,
                "violations": [],
                "repair_prompt": None,
            }

        violations = []
        valid_count = 0

        for c in citations:
            rec_id = str(c.get("record_id") or c.get("id") or "")
            metric_key = str(c.get("metric_key") or c.get("metric") or "")
            claimed_val = c.get("value") or c.get("claimed_value") or c.get("observed_value")

            # Check if metric exists in ground truth
            actual_val = None
            if rec_id and rec_id in ground_truth:
                record_data = ground_truth[rec_id]
                if isinstance(record_data, dict):
                    actual_val = record_data.get(metric_key, record_data.get("amount", record_data.get("value")))
                else:
                    actual_val = record_data
            elif metric_key in ground_truth:
                actual_val = ground_truth[metric_key]
            
            if actual_val is None:
                # Metric or record not found in ground truth store
                violations.append({
                    "record_id": rec_id,
                    "metric_key": metric_key,
                    "claimed_value": claimed_val,
                    "actual_value": None,
                    "reason": f"Record/metric '{rec_id or metric_key}' not found in verified database outputs."
                })
                continue

            try:
                claimed_num = float(claimed_val)
                actual_num = float(actual_val)
            except (ValueError, TypeError):
                # Non-numeric comparison
                if str(claimed_val).strip().lower() != str(actual_val).strip().lower():
                    violations.append({
                        "record_id": rec_id,
                        "metric_key": metric_key,
                        "claimed_value": claimed_val,
                        "actual_value": actual_val,
                        "reason": f"Claimed value '{claimed_val}' does not match actual '{actual_val}'."
                    })
                else:
                    valid_count += 1
                continue

            # Check numerical tolerance
            if actual_num == 0:
                diff_pct = 100.0 if claimed_num != 0 else 0.0
            else:
                diff_pct = abs((claimed_num - actual_num) / actual_num) * 100.0

            if diff_pct > tolerance_pct:
                violations.append({
                    "record_id": rec_id,
                    "metric_key": metric_key,
                    "claimed_value": claimed_num,
                    "actual_value": actual_num,
                    "variance_pct": round(diff_pct, 2),
                    "reason": f"Claimed value {claimed_num:,.2f} deviates from actual {actual_num:,.2f} by {diff_pct:.2f}% (tolerance: {tolerance_pct}%)."
                })
            else:
                valid_count += 1

        is_valid = len(violations) == 0
        repair_prompt = cls.build_repair_prompt(violations) if not is_valid else None

        return {
            "is_valid": is_valid,
            "valid_count": valid_count,
            "invalid_count": len(violations),
            "violations": violations,
            "repair_prompt": repair_prompt,
        }

    @staticmethod
    def build_repair_prompt(violations: List[Dict[str, Any]]) -> str:
        """
        Constructs a structured self-correction prompt for the LLM.
        """
        v_lines = []
        for v in violations:
            rec = f" [Record: {v['record_id']}]" if v.get('record_id') else ""
            act = f", Verified DB value: {v['actual_value']}" if v.get('actual_value') is not None else " (Not found in DB)"
            v_lines.append(f"- Metric: {v.get('metric_key')}{rec}. Claimed: {v.get('claimed_value')}{act}. Reason: {v.get('reason')}")

        return (
            "<citation_repair_request>\n"
            "Your previous report output contained unverified or mathematically mismatched citations:\n"
            + "\n".join(v_lines) +
            "\n\nPlease correct your findings using ONLY the verified values from the database outputs. "
            "Ensure all figures strictly reconcile with the tool records.\n"
            "</citation_repair_request>"
        )
