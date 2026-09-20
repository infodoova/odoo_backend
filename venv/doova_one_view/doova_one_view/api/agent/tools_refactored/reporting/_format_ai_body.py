# doova_one_view/api/agent/tools_refactored/reporting/_format_ai_body.py

import re
import logging
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger(__name__)


def _escape_md_pipe(val: Any) -> str:
    """Escapes pipe characters in markdown table cells and normalizes newlines."""
    if val is None:
        return "—"
    s = str(val).strip()
    return s.replace("|", "&#124;").replace("\n", "<br>") if s else "—"


def _format_currency_num(amt: Any, currency: str = "XAF") -> str:
    """Formats a number or string into a clean currency representation."""
    if amt is None:
        return "—"
    if isinstance(amt, (int, float)):
        return f"{currency} {amt:,.2f}" if isinstance(amt, float) and not amt.is_integer() else f"{currency} {int(amt):,}"
    amt_str = str(amt).strip()
    if re.match(r'^-?\d+(?:\.\d+)?$', amt_str):
        try:
            f = float(amt_str)
            return f"{currency} {f:,.2f}" if not f.is_integer() else f"{currency} {int(f):,}"
        except ValueError:
            pass
    return amt_str


def _humanize_key(key: str) -> str:
    """Converts a snake_case or camelCase key into a human-readable title."""
    key_clean = re.sub(r'([a-z0-9])([A-Z])', r'\1 \2', key)
    key_clean = key_clean.replace("_", " ").strip()

    # Common financial and business abbreviations
    abbrev_map = {
        "sku": "SKU",
        "kpi": "KPI",
        "kpis": "KPIs",
        "cv": "CV",
        "dso": "DSO",
        "gm": "GM",
        "ebitda": "EBITDA",
        "ebit": "EBIT",
        "cogs": "COGS",
        "po": "PO",
        "btu": "BTU",
        "mom": "MoM",
        "yoy": "YoY",
        "ytd": "YTD",
        "p10": "P10",
        "p50": "P50",
        "p90": "P90",
        "pct": "%",
        "id": "ID",
        "gl": "GL",
        "tb": "Trial Balance",
        "ar": "AR",
        "ap": "AP",
        "vat": "VAT",
        "sod": "SoD",
        "mad": "MAD",
        "isa": "ISA",
    }
    words = [abbrev_map.get(w.lower(), w.title()) for w in key_clean.split()]
    return " ".join(words)


def _is_monetary_key(k: str) -> bool:
    """Intelligently detects whether a key represents a monetary currency value."""
    k_lower = k.lower()
    non_monetary_markers = (
        "days", "units", "count", "cnt", "rate", "pct", "percentage", "share",
        "ratio", "score", "weight", "prob", "probability", "id", "index", "code",
        "user", "transactions", "txns", "population", "sample"
    )
    if any(m in k_lower for m in non_monetary_markers):
        return False
    monetary_markers = (
        "spend", "value", "amount", "cost", "price", "revenue", "capital",
        "balance", "budget", "exposure", "materiality", "recoverable",
        "at_risk", "liability", "misstatement", "factual", "judgmental",
        "projected", "debit", "credit", "profit", "loss", "ebit", "cogs", "opex"
    )
    return any(m in k_lower for m in monetary_markers)


def _is_percentage_key(k: str) -> bool:
    """Intelligently detects whether a key represents a ratio or percentage."""
    k_lower = k.lower()
    return any(p in k_lower for p in ("rate", "pct", "percentage", "share", "margin", "probability", "prob", "weight"))


def _format_dynamic_cell(val: Any, key_hint: str = "", curr: str = "XAF") -> str:
    """Intelligently formats an individual data cell based on key heuristics and value type."""
    if val is None:
        return "—"
    if isinstance(val, bool):
        return "YES" if val else "NO"
    if isinstance(val, (int, float)):
        if _is_monetary_key(key_hint):
            return _format_currency_num(val, curr)
        if _is_percentage_key(key_hint):
            return f"{val:.1f}%" if isinstance(val, float) and not val.is_integer() else f"{int(val)}%" if val == int(val) else f"{val}%"
        if isinstance(val, float):
            return f"{val:,.2f}" if not val.is_integer() else f"{int(val):,}"
        return f"{val:,}"

    s = str(val).strip()
    if not s:
        return "—"
    if re.match(r'^-?\d+(?:\.\d+)?$', s):
        try:
            num = float(s)
            if _is_monetary_key(key_hint):
                return _format_currency_num(num, curr)
            if _is_percentage_key(key_hint):
                return f"{num:.1f}%" if not num.is_integer() else f"{int(num)}%"
            return f"{num:,.2f}" if not num.is_integer() else f"{int(num):,}"
        except ValueError:
            pass
    return _escape_md_pipe(s)


def _render_dynamic_table(headers: List[str], rows: List[List[str]], alignments: Optional[List[str]] = None) -> List[str]:
    """Generates clean Markdown table lines from headers and rows."""
    if not headers or not rows:
        return []

    lines = []
    lines.append("| " + " | ".join(headers) + " |")

    if alignments and len(alignments) == len(headers):
        sep_cells = alignments
    else:
        sep_cells = [":---" for _ in headers]
    lines.append("| " + " | ".join(sep_cells) + " |")

    for row in rows:
        padded_row = row + ["—"] * max(0, len(headers) - len(row))
        lines.append("| " + " | ".join(padded_row[:len(headers)]) + " |")
    lines.append("")
    return lines


def format_dynamic_payload(payload: Dict[str, Any], prefix_title: Optional[str] = None) -> List[str]:
    """
    Universally and dynamically renders ANY structured payload dictionary
    (forecast, audit, inventory, diagnostic analysis, financial ratio pack, or arbitrary custom JSON)
    into publication-grade, C-suite executive Markdown.

    Key Architectural Principles:
    1. Schema-Agnostic: Never assumes a single rigid schema; dynamically discovers columns, mappings, and lists.
    2. Deep Field Preservation: Never drops extra or custom fields on findings, materiality, or arbitrary dicts.
    3. Intelligent Type Heuristics: Auto-detects currencies, percentages, counts, statuses, and badges.
    4. Strict Telemetry Guardrail: 'token_usage' is strictly excluded from output.
    """
    if not isinstance(payload, dict) or not payload:
        return []

    lines: List[str] = []
    curr = payload.get("currency") or "XAF"

    # Consumed keys registry to avoid duplicate rendering in fallback
    consumed_keys = {
        "title", "name", "header", "value", "projected_value", "headline_value", "total_amount",
        "period", "date_range", "timeframe", "window", "confidence", "confidence_score", "score",
        "currency", "summary", "overview", "executive_summary", "token_usage", "role", "message_type",
        "attachments", "citations", "created_at", "updated_at", "session_id", "id", "kpis", "body_html",
        "status", "grade", "priority", "depth", "audit_focus", "score_calculation", "trend",
        "primary_metric", "focus_area", "dimension", "scope_label"
    }

    # 1. Headline Title
    title = payload.get("title") or payload.get("name") or payload.get("header") or prefix_title or "Executive Strategic Outlook"
    lines.append(f"## {title}")

    # Determine domain context for contextual labeling
    is_audit = bool(
        payload.get("findings")
        or payload.get("materiality")
        or payload.get("pillar_scores")
        or payload.get("misstatement_summary")
        or payload.get("quantified_exposure")
        or payload.get("benford_analysis")
        or payload.get("segregation_of_duties")
        or (payload.get("status") in ("Verified", "Attention Needed", "Issues Found", "Critical") and "score" in payload)
        or "audit" in str(payload.get("priority", "")).lower()
        or "audit" in str(payload.get("title", "")).lower()
    )
    is_forecast = bool(
        payload.get("revenue_bridge")
        or payload.get("reorder_recommendations")
        or payload.get("scenarios")
        or payload.get("demand_scenarios")
        or payload.get("inventory_position")
        or "forecast" in str(payload.get("title", "")).lower()
        or "projection" in str(payload.get("title", "")).lower()
    )

    # 2. Executive Metadata Summary Banner (Unified & Dynamic across all domains)
    meta_parts = []

    # Primary headline figure / metric
    val_candidate = payload.get("value") or payload.get("projected_value") or payload.get("headline_value") or payload.get("total_amount") or payload.get("primary_metric")
    if val_candidate:
        if is_forecast and not payload.get("trend"):
            meta_parts.append(f"**Projected Value:** {val_candidate}")
        else:
            meta_parts.append(f"**Primary Metric:** {val_candidate}")

    if payload.get("trend"):
        meta_parts.append(f"**Trend:** {payload['trend']}")

    if payload.get("score") is not None:
        score_lbl = "Audit Score" if is_audit else "Score"
        meta_parts.append(f"**{score_lbl}:** {payload['score']}/100")

    if payload.get("status"):
        meta_parts.append(f"**Status:** {payload['status']}")

    if payload.get("grade"):
        meta_parts.append(f"**Grade:** {payload['grade']}")

    conf_candidate = payload.get("confidence") or payload.get("confidence_score")
    if conf_candidate is not None:
        conf_str = f"{conf_candidate}%" if str(conf_candidate).isdigit() else str(conf_candidate)
        meta_parts.append(f"**Confidence Level:** {conf_str}")

    if payload.get("priority"):
        meta_parts.append(f"**Priority:** {payload['priority']}")

    if payload.get("depth"):
        meta_parts.append(f"**Depth:** {payload['depth']}")

    period_candidate = payload.get("period") or payload.get("date_range") or payload.get("timeframe") or payload.get("window")
    if period_candidate:
        p_lbl = "Forecast Period" if is_forecast else "Audit Window" if is_audit else "Period"
        meta_parts.append(f"**{p_lbl}:** {period_candidate}")

    if curr and curr != "XAF":
        meta_parts.append(f"**Currency:** {curr}")

    # Discover and include any extra top-level scalar metadata fields
    for m_key, m_val in payload.items():
        if m_key not in consumed_keys and isinstance(m_val, (str, int, float, bool)) and not m_key.startswith("_"):
            val_str = str(m_val).strip()
            if val_str and len(val_str) <= 35:
                meta_parts.append(f"**{_humanize_key(m_key)}:** {val_str}")
                consumed_keys.add(m_key)

    if meta_parts:
        lines.append("  |  ".join(meta_parts))
        lines.append("")

    if payload.get("audit_focus"):
        lines.append(f"**Audit Focus:** {payload['audit_focus']}")
        lines.append("")

    if payload.get("score_calculation"):
        lines.append(f"**Score Deduction Arithmetic & Ceilings:** {payload['score_calculation']}")
        lines.append("")

    # Executive Summary / Overview Narrative
    summary_text = payload.get("summary") or payload.get("overview") or payload.get("executive_summary")
    if summary_text and isinstance(summary_text, str) and summary_text.strip():
        lines.append("### Executive Summary")
        lines.append("")
        lines.append(summary_text.strip())
        lines.append("")

    # 3. Intelligent Domain Section Processors (Fully Dynamic & Schema-Resilient)

    # A. Operational Indicators / Metrics Table
    metrics = payload.get("metrics") or payload.get("kpis") or payload.get("operational_indicators")
    if isinstance(metrics, list) and metrics:
        consumed_keys.update({"metrics", "kpis", "operational_indicators"})
        if isinstance(metrics[0], dict) and ("label" in metrics[0] or "value" in metrics[0]) and ("benchmark" in metrics[0] or "status" in metrics[0]):
            lines.append("### Operational Indicators & Model Benchmarks")
            lines.append("")
            headers = ["Metric Indicator", "Forecast Value", "Status", "Target / Benchmark"]
            aligns = [":---", ":---", ":---:", ":---"]
            rows = []
            for m in metrics:
                if isinstance(m, dict):
                    lbl = _escape_md_pipe(m.get("label", "Metric"))
                    val = _escape_md_pipe(m.get("value", "—"))
                    status = _escape_md_pipe(m.get("status", "ok")).upper()
                    bm = _escape_md_pipe(m.get("benchmark", "—"))
                    rows.append([lbl, f"**{val}**", status, bm])
            lines.extend(_render_dynamic_table(headers, rows, aligns))
        elif isinstance(metrics[0], dict):
            lines.append("### Operational Indicators & Performance Metrics")
            lines.append("")
            sub_headers = [k for k in metrics[0].keys() if not k.startswith("_")]
            rows = [[_format_dynamic_cell(m.get(h), h, curr) for h in sub_headers] for m in metrics if isinstance(m, dict)]
            lines.extend(_render_dynamic_table([_humanize_key(h) for h in sub_headers], rows))

    # B. Strategic Insights
    insights = payload.get("insights") or payload.get("strategic_insights") or payload.get("key_insights")
    if isinstance(insights, list) and insights:
        consumed_keys.update({"insights", "strategic_insights", "key_insights"})
        sec_name = "Key Insights" if (payload.get("trend") or not is_forecast) else "Executive Strategic Insights"
        lines.append(f"### {sec_name}")
        lines.append("")
        for item in insights:
            if isinstance(item, str) and item.strip():
                lines.append(f"- {item.strip()}")
            elif isinstance(item, dict):
                t = item.get("title") or item.get("headline") or item.get("name") or "Observation"
                d = item.get("description") or item.get("text") or item.get("desc") or ""
                lines.append(f"- **{t}**: {d}" if d else f"- **{t}**")
        lines.append("")

    # C. Scenarios Modeling
    scenarios_data = payload.get("scenarios") or payload.get("demand_scenarios")
    if isinstance(scenarios_data, dict) and scenarios_data:
        consumed_keys.update({"scenarios", "demand_scenarios"})
        lines.append("### Scenario Modeling & Sensitivity Bands")
        lines.append("")
        headers = ["Scenario Case", "Probability", "Projected Outcome", "Sensitivity Drivers"]
        aligns = [":---", ":---:", ":---", ":---"]
        rows = []
        ordered_keys = sorted(
            scenarios_data.keys(),
            key=lambda k: 0 if ("bear" in k.lower() or "p10" in k.lower() or "down" in k.lower())
            else (1 if ("base" in k.lower() or "p50" in k.lower() or "expected" in k.lower()) else 2)
        )
        for case_key in ordered_keys:
            sc = scenarios_data[case_key]
            if isinstance(sc, dict):
                c_lbl = _escape_md_pipe(sc.get("label", case_key.replace("_", " ").title()))
                prob = sc.get("probability", "—")
                prob_str = f"{prob}%" if str(prob).isdigit() else str(prob)
                outcome = _escape_md_pipe(sc.get("value", sc.get("projected", "—")))
                drivers_list = sc.get("drivers") or sc.get("factors") or []
                if isinstance(drivers_list, list) and drivers_list:
                    drivers_str = "<br>&bull; ".join([_escape_md_pipe(d) for d in drivers_list])
                    drivers_str = f"&bull; {drivers_str}"
                else:
                    drivers_str = "—"
                rows.append([f"**{c_lbl}**", prob_str, f"**{outcome}**", drivers_str])
        lines.extend(_render_dynamic_table(headers, rows, aligns))

    # D. Revenue / Financial Waterfall Bridge
    bridge = payload.get("revenue_bridge") or payload.get("waterfall") or payload.get("bridge")
    if isinstance(bridge, list) and bridge:
        consumed_keys.update({"revenue_bridge", "waterfall", "bridge"})
        lines.append("### Strategic Revenue Bridge Waterfall")
        lines.append("")
        headers = ["Line Item", "Category", "Amount", "Calculation Basis"]
        aligns = [":---", ":---:", ":---:", ":---"]
        rows = []
        for row in bridge:
            if isinstance(row, dict):
                lbl = _escape_md_pipe(row.get("label", row.get("name", "Line Item")))
                b_type = _escape_md_pipe(row.get("type", row.get("category", "step"))).title()
                basis = _escape_md_pipe(row.get("basis", row.get("description", "—")))
                amt = row.get("amount", row.get("value"))
                amt_str = _escape_md_pipe(_format_currency_num(amt, curr))
                rows.append([lbl, b_type, f"**{amt_str}**", basis])
        lines.extend(_render_dynamic_table(headers, rows, aligns))

    # E. Inventory Working Capital Position
    inv_pos = payload.get("inventory_position") or payload.get("working_capital_position")
    if isinstance(inv_pos, dict) and inv_pos:
        consumed_keys.update({"inventory_position", "working_capital_position"})
        lines.append("### Inventory Working Capital Position")
        lines.append("")
        headers = ["Working Capital Parameter", "Evaluated Allocation"]
        aligns = [":---", ":---"]
        rows = []
        for k, v in inv_pos.items():
            k_title = _escape_md_pipe(_humanize_key(k))
            v_val = _escape_md_pipe(_format_currency_num(v, curr) if isinstance(v, (int, float)) else str(v))
            rows.append([k_title, f"**{v_val}**"])
        lines.extend(_render_dynamic_table(headers, rows, aligns))

    # F. Prioritized SKU Reorder Schedule
    reorder = payload.get("reorder_recommendations") or payload.get("replenishment_orders")
    if isinstance(reorder, list) and reorder:
        consumed_keys.update({"reorder_recommendations", "replenishment_orders"})
        lines.append("### Prioritized SKU Replenishment & Reorder Schedule")
        lines.append("")
        headers = ["SKU", "Class", "Lead Time", "Stockout Risk", "Current Stock", "Reorder Point", "Order Units", "Order Spend"]
        aligns = [":---", ":---:", ":---:", ":---:", ":---:", ":---:", ":---:", ":---"]
        rows = []
        for r in reorder:
            if isinstance(r, dict):
                sku = _escape_md_pipe(r.get("sku", r.get("product_name", "SKU")))
                abc = _escape_md_pipe(r.get("abc_class", r.get("class", "—")))
                lt = _escape_md_pipe(f"{r.get('lead_time_days', '—')} Days" if r.get('lead_time_days') is not None else "—")
                sr = _escape_md_pipe(f"{r.get('stockout_risk_days', '—')} Days" if r.get('stockout_risk_days') is not None else "—")
                cs = _escape_md_pipe(f"{int(float(r['current_stock_units'])):,}" if r.get("current_stock_units") is not None else "0")
                rp = _escape_md_pipe(f"{int(float(r['reorder_point_units'])):,}" if r.get("reorder_point_units") is not None else "—")
                ou = _escape_md_pipe(f"{int(float(r['recommended_order_units'])):,}" if r.get("recommended_order_units") is not None else "—")
                spend_raw = r.get("recommended_order_value", r.get("order_spend"))
                spend = _escape_md_pipe(_format_currency_num(spend_raw, curr) if spend_raw is not None else "—")
                rows.append([f"**{sku}**", abc, lt, sr, cs, rp, ou, f"**{spend}**"])
        lines.extend(_render_dynamic_table(headers, rows, aligns))

    # G. Strategic Model Assumptions
    assumptions = payload.get("assumptions") or payload.get("model_assumptions")
    if isinstance(assumptions, list) and assumptions:
        consumed_keys.update({"assumptions", "model_assumptions"})
        lines.append("### Strategic Model Assumptions & Sensitivities")
        lines.append("")
        headers = ["Core Assumption", "Empirical Baseline", "Sensitivity Impact"]
        aligns = [":---", ":---", ":---"]
        rows = []
        for a in assumptions:
            if isinstance(a, dict):
                assm = _escape_md_pipe(a.get("assumption", a.get("name", "Assumption")))
                basis = _escape_md_pipe(a.get("basis", a.get("rationale", "—")))
                sens = _escape_md_pipe(a.get("sensitivity", a.get("impact", "—")))
                rows.append([f"**{assm}**", basis, sens])
        lines.extend(_render_dynamic_table(headers, rows, aligns))

    # H. Risk Assessment & Mitigation Controls
    risks = payload.get("risks") or payload.get("risk_assessment")
    if isinstance(risks, list) and risks:
        consumed_keys.update({"risks", "risk_assessment"})
        lines.append("### Risk Assessment & Mitigation Controls")
        lines.append("")
        headers = ["Risk Exposure", "Financial Exposure", "Likelihood", "Actionable Mitigation"]
        aligns = [":---", ":---:", ":---:", ":---"]
        rows = []
        for r in risks:
            if isinstance(r, dict):
                risk_txt = _escape_md_pipe(r.get("risk", r.get("title", "Risk")))
                exp = _escape_md_pipe(r.get("exposure", r.get("financial_impact", "—")))
                lh = _escape_md_pipe(r.get("likelihood", r.get("probability", "medium"))).upper()
                mit = _escape_md_pipe(r.get("mitigation", r.get("action", "—")))
                rows.append([f"**{risk_txt}**", exp, lh, mit])
        lines.extend(_render_dynamic_table(headers, rows, aligns))

    # I. Phased Execution Roadmap
    steps = payload.get("steps") or payload.get("action_plan") or payload.get("execution_roadmap")
    if isinstance(steps, list) and steps:
        consumed_keys.update({"steps", "action_plan", "execution_roadmap"})
        lines.append("### Phased Strategic Execution Roadmap")
        lines.append("")
        headers = ["Phase & Window", "Functional Owner", "Execution Milestone & Target Metric", "Value at Stake"]
        aligns = [":---", ":---", ":---", ":---"]
        rows = []
        for s in steps:
            if isinstance(s, dict):
                p_title = _escape_md_pipe(s.get("title", f"Phase {s.get('phase', '')}"))
                win = _escape_md_pipe(s.get("window", s.get("timeline", "")))
                owner = _escape_md_pipe(s.get("owner", s.get("lead", "Finance / Ops")))
                desc = _escape_md_pipe(s.get("description", s.get("desc", "")))
                target = _escape_md_pipe(s.get("target_metric", s.get("target", "")))
                val_stake = _escape_md_pipe(s.get("value_at_stake", s.get("impact", "—")))

                action_cell = desc
                if target:
                    action_cell += f"<br><strong>Target:</strong> {target}"

                phase_col = f"**{p_title}**"
                if win:
                    phase_col += f"<br><em>({win})</em>"

                rows.append([phase_col, owner, action_cell, f"**{val_stake}**"])
        lines.extend(_render_dynamic_table(headers, rows, aligns))

    # J. Alerts Section (Critical Integrity & Risk Alerts)
    alerts = payload.get("alerts") or payload.get("warnings")
    if isinstance(alerts, list) and alerts:
        consumed_keys.update({"alerts", "warnings"})
        lines.append("### Critical Integrity & Risk Alerts")
        lines.append("")
        for a in alerts:
            if isinstance(a, dict):
                t = a.get("text") or a.get("title") or "Alert"
                s = a.get("sub") or a.get("subtitle") or a.get("description") or ""
                lines.append(f"- **{t}**: {s}" if s else f"- **{t}**")
            elif isinstance(a, str) and a.strip():
                lines.append(f"- {a.strip()}")
        lines.append("")

    # K. Detailed Findings & Ledger Governance / Diagnostic Decomposition
    findings = payload.get("findings") or payload.get("details") or payload.get("anomalies") or payload.get("exceptions")
    if isinstance(findings, list) and findings:
        consumed_keys.update({"findings", "details", "anomalies", "exceptions"})
        sec_title = "Detailed Forensic Findings & Ledger Governance" if is_audit else "Diagnostic Findings & Performance Decomposition"
        lines.append(f"### {sec_title}")
        lines.append("")

        # High-level summary table if multiple structured items exist
        if len(findings) > 1 and isinstance(findings[0], dict):
            # Check if findings follow the audit procedure/exposure schema or general diagnostic schema
            has_audit_cols = any("procedure_ref" in f or "exposure_value" in f or "assertion" in f for f in findings if isinstance(f, dict))
            if has_audit_cols:
                f_headers = ["Procedure", "Finding Title", "Severity", "Classification", "Assertion", "Exposure", "Owner"]
                f_aligns = [":---:", ":---", ":---:", ":---", ":---", ":---:", ":---"]
                f_rows = []
                for idx, f in enumerate(findings, 1):
                    if isinstance(f, dict):
                        ref = _escape_md_pipe(f.get("procedure_ref") or f"F-{idx:02d}")
                        t = _escape_md_pipe(f.get("title", f"Finding #{idx}"))
                        sev = _escape_md_pipe(str(f.get("severity", "review")).upper())
                        def_cls = _escape_md_pipe(_humanize_key(f.get("deficiency_class", "observation")))
                        ass = _escape_md_pipe(f.get("assertion", "—"))
                        exp_val = f.get("exposure_value")
                        exp_str = _escape_md_pipe(_format_currency_num(exp_val, curr) if exp_val is not None else "—")
                        own = _escape_md_pipe(f.get("owner", "Finance"))
                        f_rows.append([ref, f"**{t}**", sev, def_cls, ass, exp_str, own])
                lines.extend(_render_dynamic_table(f_headers, f_rows, f_aligns))

        # Itemized finding/detail cards with recursive attribute preservation
        for idx, f in enumerate(findings, 1):
            if isinstance(f, dict):
                sev = (f.get("severity") or "review").upper() if f.get("severity") else ""
                f_title = f.get("title") or f"Finding #{idx}"
                def_cls = _humanize_key(f.get("deficiency_class") or "") if f.get("deficiency_class") else ""

                if sev and def_cls:
                    lines.append(f"#### {idx}. [{sev}] {f_title} — {def_cls}")
                elif sev:
                    lines.append(f"#### {idx}. [{sev}] {f_title}")
                else:
                    lines.append(f"#### {idx}. {f_title}")
                lines.append("")

                f_consumed = {"title", "severity", "deficiency_class", "description", "desc", "recommendation", "owner", "evidence", "assertion", "pillar", "procedure_ref", "exposure_value", "vs_materiality", "population_tested"}

                meta_bullets = []
                if f.get("assertion"):
                    meta_bullets.append(f"**Assertion:** {f['assertion']}")
                if f.get("pillar"):
                    meta_bullets.append(f"**Pillar:** {_humanize_key(f['pillar'])}")
                if f.get("procedure_ref"):
                    meta_bullets.append(f"**Procedure:** {f['procedure_ref']}")
                if meta_bullets:
                    lines.append("- " + "  |  ".join(meta_bullets))

                exp_bullets = []
                if f.get("exposure_value") is not None:
                    exp_bullets.append(f"**Exposure Value:** {_format_currency_num(f['exposure_value'], curr)}")
                if f.get("vs_materiality"):
                    exp_bullets.append(f"**Vs Materiality:** {f['vs_materiality']}")
                if f.get("population_tested"):
                    exp_bullets.append(f"**Population Tested:** {f['population_tested']}")
                if exp_bullets:
                    lines.append("- " + "  |  ".join(exp_bullets))

                evidence = f.get("evidence")
                if isinstance(evidence, list) and evidence:
                    ev_str = ", ".join(f"`{e}`" for e in evidence)
                    lines.append(f"- **Audit Evidence Trace:** {ev_str}")
                elif isinstance(evidence, str) and evidence:
                    lines.append(f"- **Audit Evidence Trace:** `{evidence}`")

                desc = f.get("description") or f.get("desc")
                if desc:
                    lines.append(f"- **Root Cause & Observation:** {desc}" if is_audit else desc)
                    if not is_audit:
                        lines.append("")

                rec = f.get("recommendation") or f.get("action")
                if rec:
                    owner_str = f" *(Accountable Owner: {f.get('owner')})*" if f.get("owner") else ""
                    lines.append(f"- **Remediation Recommendation:** {rec}{owner_str}")

                # Dynamically discover and render ANY remaining attributes on the finding card
                for sub_k, sub_v in f.items():
                    if sub_k not in f_consumed and not sub_k.startswith("_") and sub_v is not None:
                        lines.append(f"- **{_humanize_key(sub_k)}:** {_format_dynamic_cell(sub_v, sub_k, curr)}")

                lines.append("")
            elif isinstance(f, str) and f.strip():
                lines.append(f"- {f.strip()}")
                lines.append("")

    # L. Strategic Levers & Interventions (Non-Audit or General Analysis)
    levers = payload.get("levers") or payload.get("recommendations") or payload.get("remediation")
    if isinstance(levers, list) and levers and not payload.get("findings"):
        consumed_keys.update({"levers", "recommendations", "remediation"})
        lines.append("### Strategic Optimization Levers & Interventions")
        lines.append("")
        for idx, l in enumerate(levers, 1):
            if isinstance(l, dict):
                l_title = l.get("title") or f"Lever #{idx}"
                l_desc = l.get("description") or l.get("desc") or ""
                lines += [f"#### {idx}. {l_title}", l_desc, ""]
            elif isinstance(l, str):
                lines.append(f"- **Lever {idx}**: {l}")
        lines.append("")

    # M. Quantitative Materiality Framework (ISA 320)
    mat = payload.get("materiality") or payload.get("materiality_framework")
    if isinstance(mat, dict) and (mat.get("overall") or mat.get("benchmark")):
        consumed_keys.update({"materiality", "materiality_framework"})
        lines.append("### Quantitative Materiality Framework (ISA 320)")
        lines.append("")
        m_headers = ["Benchmark", "Base Value", "Applied Rate", "Overall Materiality", "Performance Materiality (75%)", "Clearly Trivial (5%)"]
        m_aligns = [":---", ":---:", ":---:", ":---:", ":---:", ":---:"]
        bm = _escape_md_pipe(_humanize_key(mat.get("benchmark", "Pre-Tax Income")))
        bm_val = _escape_md_pipe(_format_currency_num(mat.get("benchmark_value"), curr))
        rate = _escape_md_pipe(str(mat.get("rate_applied", "5%")))
        om = _escape_md_pipe(_format_currency_num(mat.get("overall"), curr))
        pm = _escape_md_pipe(_format_currency_num(mat.get("performance"), curr))
        ct = _escape_md_pipe(_format_currency_num(mat.get("clearly_trivial"), curr))
        lines.extend(_render_dynamic_table(m_headers, [[bm, bm_val, rate, f"**{om}**", f"**{pm}**", ct]], m_aligns))
        if mat.get("rationale"):
            lines.append(f"- **Benchmarking Methodology Rationale:** {mat['rationale']}")
            lines.append("")

    # N. Misstatement Schedule & Materiality Conclusion
    ms = payload.get("misstatement_summary") or payload.get("misstatements")
    if isinstance(ms, dict) and ("total" in ms or "factual" in ms):
        consumed_keys.update({"misstatement_summary", "misstatements"})
        lines.append("### Misstatement Schedule & Materiality Conclusion")
        lines.append("")
        ms_headers = ["Factual Misstatements", "Judgmental Misstatements", "Projected Misstatements", "Total Accumulated", "Materiality Breached?"]
        ms_aligns = [":---:", ":---:", ":---:", ":---:", ":---:"]
        fact = _escape_md_pipe(_format_currency_num(ms.get("factual", 0), curr))
        judg = _escape_md_pipe(_format_currency_num(ms.get("judgmental", 0), curr))
        proj = _escape_md_pipe(_format_currency_num(ms.get("projected", 0), curr))
        tot = _escape_md_pipe(_format_currency_num(ms.get("total", 0), curr))
        breached = "YES (EXCEEDS OVERALL)" if ms.get("exceeds_overall_materiality") else "NO (WITHIN TOLERANCE)"
        lines.extend(_render_dynamic_table(ms_headers, [[fact, judg, proj, f"**{tot}**", breached]], ms_aligns))
        if ms.get("conclusion"):
            lines.append(f"- **Audit Conclusion:** {ms['conclusion']}")
            lines.append("")

    # O. Five-Pillar Governance & Ledger Integrity Evaluation
    pillars = payload.get("pillar_scores") or payload.get("governance_pillars")
    if pillars:
        consumed_keys.update({"pillar_scores", "governance_pillars"})
        lines.append("### Five-Pillar Governance & Ledger Integrity Evaluation")
        lines.append("")
        p_headers = ["Audit Governance Pillar", "Score", "Weight", "Evaluation Summary"]
        p_aligns = [":---", ":---:", ":---:", ":---"]
        p_rows = []
        if isinstance(pillars, list):
            for p in pillars:
                if isinstance(p, dict):
                    p_name = _escape_md_pipe(_humanize_key(p.get("pillar", "Pillar")))
                    p_score = p.get("score", "—")
                    p_score_str = f"{p_score}/100" if str(p_score).isdigit() else str(p_score)
                    p_wt = p.get("weight", "—")
                    p_wt_str = f"{p_wt}%" if str(p_wt).isdigit() else str(p_wt)
                    p_sum = _escape_md_pipe(p.get("summary", "—"))
                    p_rows.append([f"**{p_name}**", f"**{p_score_str}**", p_wt_str, p_sum])
        elif isinstance(pillars, dict):
            for p_key, p_val in pillars.items():
                p_name = _escape_md_pipe(_humanize_key(p_key))
                if isinstance(p_val, dict):
                    p_score = p_val.get("score", "—")
                    p_score_str = f"{p_score}/100" if str(p_score).isdigit() else str(p_score)
                    p_wt = p_val.get("weight", "—")
                    p_wt_str = f"{p_wt}%" if str(p_wt).isdigit() else str(p_wt)
                    p_sum = _escape_md_pipe(p_val.get("summary", "—"))
                    p_rows.append([f"**{p_name}**", f"**{p_score_str}**", p_wt_str, p_sum])
                else:
                    p_score_str = f"{p_val}/100" if str(p_val).isdigit() else str(p_val)
                    p_rows.append([f"**{p_name}**", f"**{p_score_str}**", "—", "—"])
        if p_rows:
            lines.extend(_render_dynamic_table(p_headers, p_rows, p_aligns))

    # P. Quantified Financial Exposure & Capital at Risk
    qe = payload.get("quantified_exposure") or payload.get("financial_exposure")
    if isinstance(qe, dict) and ("recoverable" in qe or "at_risk" in qe or "exposure" in qe):
        consumed_keys.update({"quantified_exposure", "financial_exposure"})
        lines.append("### Quantified Financial Exposure & Capital at Risk")
        lines.append("")
        qe_headers = ["Cash Recoverable", "Capital at Risk", "Unrecorded Liabilities", "Exposure Assessment Notes"]
        qe_aligns = [":---:", ":---:", ":---:", ":---"]
        rec = _escape_md_pipe(_format_currency_num(qe.get("recoverable", 0), curr))
        at_r = _escape_md_pipe(_format_currency_num(qe.get("at_risk", qe.get("exposure", 0)), curr))
        unrec = _escape_md_pipe(_format_currency_num(qe.get("unrecorded_liability", 0), curr))
        note = _escape_md_pipe(qe.get("note", "—"))
        lines.extend(_render_dynamic_table(qe_headers, [[f"**{rec}**", f"**{at_r}**", f"**{unrec}**", note]], qe_aligns))

    # Q. Statistical Conformity & Benford's Law Digit Analysis
    ba = payload.get("benford_analysis") or payload.get("benfords_law")
    if isinstance(ba, dict) and ("performed" in ba or "mad" in ba):
        consumed_keys.update({"benford_analysis", "benfords_law"})
        lines.append("### Statistical Conformity & Benford's Law Digit Analysis")
        lines.append("")
        ba_headers = ["Test Status", "Population Size", "Mean Absolute Deviation (MAD)", "Conformity Assessment"]
        ba_aligns = [":---:", ":---:", ":---:", ":---:"]
        status_str = "Performed" if ba.get("performed") else "Not Performed"
        pop_size = f"{int(float(ba.get('population_size', 0))):,}" if ba.get("population_size") else "—"
        mad_val = f"{float(ba.get('mad', 0)):.4f}" if ba.get("mad") is not None else "—"
        conf_str = _escape_md_pipe(str(ba.get("conformity", "—")).upper())
        lines.extend(_render_dynamic_table(ba_headers, [[status_str, pop_size, mad_val, f"**{conf_str}**"]], ba_aligns))
        if ba.get("note"):
            lines.append(f"- **Digit Distribution Notes:** {ba['note']}")
            lines.append("")

    # R. Segregation of Duties & Conflicting Control Permissions
    sod = payload.get("segregation_of_duties") or payload.get("sod")
    if sod:
        consumed_keys.update({"segregation_of_duties", "sod"})
        lines.append("### Segregation of Duties & Conflicting Control Permissions")
        lines.append("")
        sod_headers = ["Conflicting Authorization Roles", "Users Affected", "Transaction Count", "Financial Exposure"]
        sod_aligns = [":---", ":---:", ":---:", ":---:"]
        sod_rows = []
        sod_list = sod if isinstance(sod, list) else sod.get("conflicts", []) if isinstance(sod, dict) else []
        for item in sod_list:
            if isinstance(item, dict):
                conf = _escape_md_pipe(item.get("conflict", item.get("role_conflict", "Conflict")))
                users = str(item.get("users_affected", 0))
                txns = str(item.get("transactions", item.get("transaction_count", 0)))
                val_num = item.get("value", item.get("exposure"))
                val_str = _escape_md_pipe(_format_currency_num(val_num, curr) if val_num is not None else "—")
                sod_rows.append([conf, users, txns, f"**{val_str}**"])
        if sod_rows:
            lines.extend(_render_dynamic_table(sod_headers, sod_rows, sod_aligns))

    # S. Audit Scope & Period Boundary Cutoff Testing
    scope_data = payload.get("scope") or payload.get("audit_scope")
    if isinstance(scope_data, dict) and (scope_data.get("start") or scope_data.get("cutoff_window") or scope_data.get("days")):
        consumed_keys.update({"scope", "audit_scope"})
        lines.append("### Audit Scope & Period Boundary Cutoff Testing")
        lines.append("")
        start = scope_data.get("start", "—")
        end = scope_data.get("end", "—")
        days = scope_data.get("days", "—")
        lbl = scope_data.get("label", "")
        days_str = f" ({days} Calendar Days)" if days != "—" else ""
        lbl_str = f" — *{lbl}*" if lbl else ""
        lines.append(f"- **Audit Date Window:** `{start}` to `{end}`{days_str}{lbl_str}")
        cutoff = scope_data.get("cutoff_window")
        if isinstance(cutoff, dict) and cutoff.get("start"):
            lines.append(f"- **Cutoff Testing Sub-Window:** `{cutoff.get('start')}` to `{cutoff.get('end')}` *(Pre/Post period boundary reconciliation)*")
        lines.append("")

    # T. Telemetry, Governance & Quality Disclosures
    dq = payload.get("data_quality") or payload.get("governance") or payload.get("engagement_telemetry")
    if isinstance(dq, dict) and (
        dq.get("notes") or dq.get("baseline_months_observed")
        or dq.get("procedures_performed") or dq.get("tools_returning_data")
        or dq.get("scope_limitations") or dq.get("coverage_note")
    ):
        consumed_keys.update({"data_quality", "governance", "engagement_telemetry"})
        if is_audit:
            lines.append("### Engagement Telemetry & Audit Quality Trail")
        else:
            lines.append("### Forecast Governance & Telemetry Audit Trail")
        lines.append("")
        if dq.get("baseline_months_observed"):
            lines.append(f"- **Baseline Observed:** {dq['baseline_months_observed']} Months")
        if "seasonally_adjusted" in dq:
            adj_str = "Seasonally Adjusted" if dq["seasonally_adjusted"] else "Unadjusted (Short Baseline)"
            lines.append(f"- **Seasonality Status:** {adj_str}")
        if "lead_time_data_available" in dq:
            lt_str = "Observed Purchase Orders" if dq["lead_time_data_available"] else "Estimated Cadence"
            lines.append(f"- **Lead Time Telemetry:** {lt_str}")
        if dq.get("tools_returning_data"):
            t_data = ", ".join(f"`{t}`" for t in dq["tools_returning_data"])
            lines.append(f"- **Connected Tools Returning Data:** {t_data}")
        if dq.get("tools_returning_empty"):
            t_empty = ", ".join(f"`{t}`" for t in dq["tools_returning_empty"])
            lines.append(f"- **Tools Returning Empty (Scope Gap):** {t_empty}")
        if dq.get("procedures_performed"):
            p_str = ", ".join(str(p) for p in dq["procedures_performed"])
            lines.append(f"- **Procedures Performed:** {p_str}")
        if dq.get("procedures_not_performed"):
            lines.append("- **Procedures Not Performed:**")
            for pnp in dq["procedures_not_performed"]:
                if isinstance(pnp, dict):
                    lines.append(f"  - `{pnp.get('ref', '—')}`: {pnp.get('reason', '—')}")
                else:
                    lines.append(f"  - {pnp}")
        if dq.get("coverage_note"):
            lines.append(f"- **Audit Population Coverage:** {dq['coverage_note']}")
        if dq.get("scope_limitations"):
            lines.append(f"- **Scope Limitations:** {dq['scope_limitations']}")
        if dq.get("notes"):
            lines.append(f"- **Audit Notes & Observations:** {dq['notes']}")
        lines.append("")

    # 4. Universal Dynamic Fallback for ANY Arbitrary, Novel, or Custom Keys
    # Ensures zero data loss for any novel JSON structures synthesized by the AI agent
    for custom_key, custom_val in payload.items():
        if custom_key in consumed_keys or custom_key.startswith("_") or not custom_val:
            continue

        clean_section_title = _humanize_key(custom_key)

        # Structure 1: List of Dictionaries -> Dynamic Auto-Discovered Markdown Table
        if isinstance(custom_val, list) and custom_val and isinstance(custom_val[0], dict):
            seen_col_keys = []
            for item in custom_val:
                if isinstance(item, dict):
                    for k in item.keys():
                        if not k.startswith("_") and not k.endswith("_formatted") and k not in seen_col_keys:
                            seen_col_keys.append(k)

            if seen_col_keys:
                lines.append(f"### {clean_section_title}")
                lines.append("")
                headers = [_humanize_key(k) for k in seen_col_keys]
                aligns = [":---:" if _is_percentage_key(k) or "status" in k.lower() else (":---:" if _is_monetary_key(k) else ":---") for k in seen_col_keys]
                rows = []
                for item in custom_val:
                    if isinstance(item, dict):
                        row_cells = [_format_dynamic_cell(item.get(k), k, curr) for k in seen_col_keys]
                        rows.append(row_cells)
                lines.extend(_render_dynamic_table(headers, rows, aligns))

        # Structure 2: List of Strings / Primitives -> Clean Bulleted List
        elif isinstance(custom_val, list) and custom_val:
            lines.append(f"### {clean_section_title}")
            lines.append("")
            for item in custom_val:
                item_str = str(item).strip()
                if item_str:
                    lines.append(f"- {item_str}")
            lines.append("")

        # Structure 3: Dictionary -> Clean Multi-Column or 2-Column Schedule Table
        elif isinstance(custom_val, dict) and custom_val:
            lines.append(f"### {clean_section_title}")
            lines.append("")
            # Check if values are nested dicts
            all_nested = all(isinstance(v, dict) for v in custom_val.values())
            if all_nested:
                inner_cols = []
                for inner_dict in custom_val.values():
                    for ik in inner_dict.keys():
                        if not ik.startswith("_") and ik not in inner_cols:
                            inner_cols.append(ik)
                headers = ["Classification / Category"] + [_humanize_key(ik) for ik in inner_cols]
                aligns = [":---"] + [":---:" for _ in inner_cols]
                rows = []
                for out_k, out_v in custom_val.items():
                    r_cells = [f"**{_humanize_key(out_k)}**"]
                    for ik in inner_cols:
                        r_cells.append(_format_dynamic_cell(out_v.get(ik), ik, curr))
                    rows.append(r_cells)
                lines.extend(_render_dynamic_table(headers, rows, aligns))
            else:
                headers = ["Dimension / Parameter", "Evaluated Allocation / Value"]
                aligns = [":---", ":---"]
                rows = []
                for sub_k, sub_v in custom_val.items():
                    if not sub_k.startswith("_") and sub_v is not None:
                        k_str = _humanize_key(sub_k)
                        v_str = _format_dynamic_cell(sub_v, sub_k, curr)
                        rows.append([k_str, f"**{v_str}**"])
                lines.extend(_render_dynamic_table(headers, rows, aligns))

        # Structure 4: Single String / Narrative Text Block
        elif isinstance(custom_val, str) and len(custom_val.strip()) > 0:
            lines.append(f"### {clean_section_title}")
            lines.append("")
            lines.append(custom_val.strip())
            lines.append("")

    return lines


# Backwards compatibility alias
format_single_forecast_payload = format_dynamic_payload


def format_dynamic_ai_analysis(
    data: Optional[Dict[str, Any]] = None,
    session_messages: Optional[List[Dict[str, Any]]] = None
) -> str:
    """
    Renders structured forecast, audit, diagnostic analysis, or multi-turn chat messages
    completely dynamically into executive Markdown.

    Completely Dynamic Behavior:
    - If session_messages is provided, renders all conversational turns chronologically:
      captures user prompts (inquiry context) and assistant responses (structured payloads + text).
    - If data is a standalone dictionary (or no session_messages), renders it dynamically.
    - Never assumes rigid single-case schemas; handles arbitrary tables, dicts, lists, and metrics.
    - Telemetry (token_usage) is strictly excluded.
    """
    all_lines: List[str] = []

    if isinstance(session_messages, list) and session_messages:
        pending_user_prompt = None
        turn_count = 0

        for msg in session_messages:
            if not isinstance(msg, dict):
                continue

            role = msg.get("role")
            content = msg.get("content") or ""
            payload = msg.get("payload")

            if role == "user":
                pending_user_prompt = content.strip() if content else None

            elif role == "assistant":
                turn_count += 1
                if turn_count > 1:
                    all_lines.append("")
                    all_lines.append("---")
                    all_lines.append("")

                if pending_user_prompt:
                    all_lines.append(f"> **Scenario / Inquiry Context:** {pending_user_prompt}")
                    all_lines.append("")
                    pending_user_prompt = None

                if isinstance(payload, dict) and payload:
                    sec_lines = format_dynamic_payload(payload, prefix_title=content if content else None)
                    all_lines.extend(sec_lines)
                elif content:
                    all_lines.append(f"## {content}")
                    all_lines.append("")

        if not all_lines and data:
            all_lines.extend(format_dynamic_payload(data))

    elif isinstance(data, dict) and data:
        all_lines.extend(format_dynamic_payload(data))

    return "\n".join(all_lines)
