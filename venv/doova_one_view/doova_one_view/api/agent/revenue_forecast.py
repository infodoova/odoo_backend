"""
Multi-domain forecasting endpoint (Revenue Growth / Inventory Demand / Resource Capacity).

Why this file changed shape
----------------------------
The original `scope` field was assumed to carry a TIME HORIZON
("Next 30 Days" / "Quarterly Growth" / "Year-End Outlook"). Product screenshots of
the actual frontend flow show a different first question entirely:

    "Which metric would you like to forecast?"
    -> Revenue Growth | Inventory Demand | Resource Capacity | (custom text)

...and that answer is what gets sent into `scope`. Time horizon is not currently a
separate user input anywhere in the flow. So `scope` is a FORECAST TARGET (what to
forecast), not a time window - a revenue bridge is meaningless for an inventory
reorder plan, and an inventory schema is meaningless for a revenue question.

What this version does differently from the previous one
----------------------------------------------------------
1.  `scope` selects one of three complete, independent methodologies - each with
    its own tool list, risk calibration, output schema, and confidence rubric.
    Nothing is force-fit into the revenue schema anymore.
2.  Time horizon is no longer read from `scope`. Each target has a sensible
    default window; an explicit `req.time_scope` / `req.horizon` is honored if the
    request model ever grows one (checked defensively, not required).
3.  The three legacy time-horizon strings ("Next 30 Days" etc.) are still accepted
    for backward compatibility - they resolve to the Revenue Growth target using
    that string as the horizon override, so a caller that never migrated does not
    break.
4.  Free text from the "Or type a custom request..." box resolves to a generic,
    clearly-labeled best-effort financial forecast rather than being silently
    misfiled under one of the three canonical targets.
5.  Every non-exact resolution (alias, legacy mapping, case-insensitive match, or
    custom fallback) produces a note that is surfaced in the response
    (data_quality.notes) and logged - never a silent default.
6.  That same never-silent pattern (canonical set -> alias table -> case-insensitive
    match -> logged, surfaced fallback) is no longer scope-only. `risk_profile` and
    the forecast horizon go through identical resolvers now (_resolve_risk_key,
    _resolve_horizon). A frontend dropdown that sends "Low Risk" instead of
    "Conservative (Safe)", or a typo'd horizon string, used to fall through a bare
    dict .get(..., default) with nothing recorded anywhere. Any input surface with
    a fixed set of expected strings is a place a caller can send something else -
    all three now behave the same way when that happens.
7.  Confidence coercion no longer fights the data-sufficiency gates it's supposed
    to respect. See _coerce_confidence - it used to clamp any value above 35 back
    up to the risk profile's floor, which silently defeated the "force
    confidence<=50 / <=55" partial-data-gate instructions for the two profiles
    (Balanced, Conservative) whose floor sits above those caps.

ASSUMPTION FLAGGED: the Risk Profile picker (Conservative (Safe) / Balanced
(Standard) / Aggressive (High Growth)) is assumed to be the same shared UI
component reused for all three targets, since only the Revenue Growth flow has
been screenshotted. Each target below reinterprets those three labels with
domain-appropriate meaning (safety stock / service level for inventory, capacity
buffer for resource capacity). Confirm this against the actual Inventory Demand
and Resource Capacity screens once available - if that picker's copy differs per
target, the *_RISK_PROFILES dicts below are the only place that needs updating.

ASSUMPTION FLAGGED (Resource Capacity): the only tools visible anywhere in this
codebase are ERP/finance tools (sales, purchase, inventory, cash, tax). There is
no headcount/staffing/production-capacity tool in evidence. "Resource Capacity"
is therefore built here as an OPERATIONAL capacity view - inventory position,
working-capital capacity, and order-fulfilment throughput - not a headcount or
labor-hours model, which this tool surface cannot support without fabricating
numbers. If "Resource Capacity" is meant to be a staffing/headcount forecast,
that needs a different tool integration and a different methodology.

ASSUMPTION FLAGGED (alias tables): TARGET_ALIASES, RISK_KEY_ALIASES and
HORIZON_ALIASES below are illustrative starting points, not a confirmed contract
with the frontend. Extend them as real unmapped values show up in
data_quality.notes / logs - that's the point of never defaulting silently.
"""

from __future__ import annotations

import calendar
import uuid
from dataclasses import dataclass, field
from datetime import date as _date, datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple

from fastapi import HTTPException
from doova_one_view.api.agent.logger import log_error


# ==========================================================================
# 1. DATE / CALENDAR HELPERS  (domain-agnostic; used by all three targets)
# ==========================================================================

def _parse_date(value: Any) -> Optional[_date]:
    if value is None or value == "":
        return None
    if isinstance(value, _date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y", "%d/%m/%Y"):
            try:
                return datetime.strptime(value.strip()[:10], fmt).date()
            except ValueError:
                continue
    return None


def _end_of_month(year: int, month: int) -> _date:
    return _date(year, month, calendar.monthrange(year, month)[1])


def _next_quarter_bounds(today: _date) -> Tuple[_date, _date]:
    current_q = (today.month - 1) // 3 + 1
    if current_q == 4:
        year, nq = today.year + 1, 1
    else:
        year, nq = today.year, current_q + 1
    start_month = 3 * (nq - 1) + 1
    return _date(year, start_month, 1), _end_of_month(year, start_month + 2)


def _fiscal_year_end(today: _date, fy_end_month: int = 12) -> _date:
    fy_end_month = min(max(int(fy_end_month or 12), 1), 12)
    year = today.year if today.month <= fy_end_month else today.year + 1
    return _end_of_month(year, fy_end_month)


def _selling_days(start: _date, end: _date) -> int:
    if end < start:
        return 0
    total_days = (end - start).days + 1
    full_weeks, remainder = divmod(total_days, 7)
    count = full_weeks * 5
    start_wd = start.weekday()
    for i in range(remainder):
        if (start_wd + i) % 7 < 5:
            count += 1
    return count


def _months_span(start: _date, end: _date) -> float:
    return round(((end - start).days + 1) / 30.4375, 1)


def _forecast_window(horizon: str, today: _date, fy_end_month: int) -> Tuple[_date, _date, str, str]:
    """Resolve a time horizon string to (start, end, label, method_hint).

    By the time this is called, `horizon` has already been through
    _resolve_horizon, so it should always be one of the three canonical
    strings below. The else-branch default here is a last-resort safety net,
    not the primary way unrecognized input gets handled anymore.
    """
    if horizon == "Quarterly Growth":
        start, end = _next_quarter_bounds(today)
        q = (start.month - 1) // 3 + 1
        return (
            start, end, f"Q{q} {start.year}",
            "Three-month forward projection over a full calendar quarter. Build "
            "month-by-month, then sum - do not project a single blended quarterly "
            "number. Seasonality must be applied per month.",
        )

    if horizon == "Year-End Outlook":
        start = today
        end = _fiscal_year_end(today, fy_end_month)
        return (
            start, end, f"FY-to-go through {end.strftime('%b %d, %Y')}",
            "Remainder-of-fiscal-year projection. Split into (a) the stub of the "
            "current month, (b) full months remaining. Report both the go-forward "
            "amount and the implied full-year landing.",
        )

    # Default: Next 30 Days
    start = today
    end = today + timedelta(days=29)
    return (
        start, end, "Next 30 Days",
        "Thirty-day forward projection. Short enough that near-term commitments "
        "(open pipeline, existing purchase orders, current backlog) dominate the "
        "historical run-rate - weight them accordingly.",
    )


@dataclass
class BaselineProfile:
    start: Optional[_date] = None
    end: Optional[_date] = None
    months: Optional[float] = None
    selling_days: Optional[int] = None
    is_bounded: bool = False
    warnings: List[str] = field(default_factory=list)

    @property
    def supports_seasonality(self) -> bool:
        return self.months is not None and self.months >= SEASONALITY_MIN_MONTHS

    @property
    def is_thin(self) -> bool:
        return self.months is not None and self.months < MIN_BASELINE_MONTHS


MIN_BASELINE_MONTHS = 3
SEASONALITY_MIN_MONTHS = 24


def _profile_baseline(start: Optional[_date], end: Optional[_date]) -> BaselineProfile:
    if not start or not end or end < start:
        return BaselineProfile(
            is_bounded=False,
            warnings=[
                "No explicit baseline range supplied - use full available history and "
                "state in the output exactly which period the tools actually returned."
            ],
        )
    months = _months_span(start, end)
    prof = BaselineProfile(
        start=start, end=end, months=months,
        selling_days=_selling_days(start, end), is_bounded=True,
    )
    if months < MIN_BASELINE_MONTHS:
        prof.warnings.append(
            f"Baseline is only {months} months. Trend and volatility measures are "
            f"statistically unreliable below {MIN_BASELINE_MONTHS} months - apply the "
            "thin-baseline confidence deduction."
        )
    if months < SEASONALITY_MIN_MONTHS:
        prof.warnings.append(
            f"Baseline is under {SEASONALITY_MIN_MONTHS} months, so no year-over-year "
            "seasonal index can be computed. State the forecast is seasonally "
            "unadjusted and list it as a named risk."
        )
    return prof


# ==========================================================================
# 2. INPUT RESOLUTION  (never-silent: canonical set -> alias -> case-insensitive
#    match -> logged + surfaced fallback. Applied identically to the three
#    enumerated inputs this endpoint accepts: forecast target, risk profile,
#    and horizon.)
# ==========================================================================

#: The only targets this engine has real, built-out methodologies for.
CANONICAL_TARGETS: Tuple[str, ...] = ("Revenue Growth", "Inventory Demand", "Resource Capacity")

DEFAULT_RISK_KEY = "Balanced (Standard)"

#: Frontend/product-copy synonyms that should resolve to a canonical target.
#: Single place to extend as the frontend's wording drifts.
TARGET_ALIASES: Dict[str, str] = {
    "Revenue Forecast": "Revenue Growth",
    "Sales Growth": "Revenue Growth",
    "Sales Forecast": "Revenue Growth",
    "Inventory Forecast": "Inventory Demand",
    "Stock Demand": "Inventory Demand",
    "Stock Forecast": "Inventory Demand",
    "Capacity Planning": "Resource Capacity",
    "Resource Planning": "Resource Capacity",
    "Capacity Forecast": "Resource Capacity",
}

#: The OLD backend contract, where `scope` meant time horizon. Kept for
#: backward compatibility: if a caller still sends one of these, treat it as a
#: Revenue Growth request using that string as the horizon override, since that
#: was the only target that ever existed when these strings were the contract.
LEGACY_TIME_SCOPE_TARGETS: Dict[str, str] = {
    "Next 30 Days": "Next 30 Days",
    "Quarterly Growth": "Quarterly Growth",
    "Year-End Outlook": "Year-End Outlook",
}


def _resolve_target(raw: str) -> Tuple[str, Optional[str], Optional[str]]:
    """
    Resolve an incoming `scope` value to (target_key, horizon_override, note).

    target_key is one of CANONICAL_TARGETS or the sentinel "Custom".
    horizon_override is set only for the legacy time-scope backward-compat path.
    note is None only for an exact canonical match; every other path (alias,
    legacy, case-insensitive, or custom fallback) returns a note so the caller
    can surface it instead of resolving silently.
    """
    if raw in CANONICAL_TARGETS:
        return raw, None, None

    if raw in LEGACY_TIME_SCOPE_TARGETS:
        horizon = LEGACY_TIME_SCOPE_TARGETS[raw]
        return "Revenue Growth", horizon, (
            f"'{raw}' is a legacy time-horizon value, not a forecast target. "
            f"Interpreted as target='Revenue Growth' with horizon='{horizon}' for "
            "backward compatibility. Update the caller to send a forecast target."
        )

    if raw in TARGET_ALIASES:
        target = TARGET_ALIASES[raw]
        return target, None, f"'{raw}' mapped to canonical target '{target}' via TARGET_ALIASES."

    lowered = raw.strip().lower()
    for canon in CANONICAL_TARGETS:
        if canon.lower() == lowered:
            # Same string, different case - still not an exact match, so it
            # still gets a note. (Previously fell through silently here.)
            return canon, None, f"'{raw}' matched canonical target '{canon}' case-insensitively."
    for alias, target in TARGET_ALIASES.items():
        if alias.lower() == lowered:
            return target, None, (
                f"'{raw}' matched alias '{alias}' case-insensitively; mapped to '{target}'."
            )
    for legacy, horizon in LEGACY_TIME_SCOPE_TARGETS.items():
        if legacy.lower() == lowered:
            return "Revenue Growth", horizon, (
                f"'{raw}' matched legacy time-scope '{legacy}' case-insensitively; "
                f"interpreted as target='Revenue Growth', horizon='{horizon}'."
            )

    # Free-text custom request, or a genuinely new target not yet in this registry.
    return "Custom", None, (
        f"'{raw}' does not match a known forecast target. Treating it as a "
        "free-text custom request and running a best-effort general financial "
        "forecast grounded in the available tools. Add it to TARGET_ALIASES or "
        "CANONICAL_TARGETS if this should be a first-class target."
    )


#: Canonical risk-profile keys, shared across all three targets' profile dicts
#: (RISK_PROFILES / INVENTORY_RISK_PROFILES / CAPACITY_RISK_PROFILES below all
#: use these same three strings as keys).
CANONICAL_RISK_KEYS: Tuple[str, ...] = (
    "Conservative (Safe)", "Balanced (Standard)", "Aggressive (High Growth)"
)

#: Frontend/product-copy synonyms that should resolve to a canonical risk key.
RISK_KEY_ALIASES: Dict[str, str] = {
    "Conservative": "Conservative (Safe)",
    "Safe": "Conservative (Safe)",
    "Low Risk": "Conservative (Safe)",
    "Defensive": "Conservative (Safe)",
    "Balanced": "Balanced (Standard)",
    "Standard": "Balanced (Standard)",
    "Moderate": "Balanced (Standard)",
    "Medium": "Balanced (Standard)",
    "Medium Risk": "Balanced (Standard)",
    "Aggressive": "Aggressive (High Growth)",
    "High Growth": "Aggressive (High Growth)",
    "Growth": "Aggressive (High Growth)",
    "High Risk": "Aggressive (High Growth)",
}


def _resolve_risk_key(raw: str) -> Tuple[str, Optional[str]]:
    """
    Resolve an incoming `risk_profile` value to (canonical_key, note).

    An ABSENT value (empty/whitespace) is expected, ordinary input - it uses
    DEFAULT_RISK_KEY with no note, same as scope defaulting to Revenue Growth
    when nothing was sent. A PRESENT value that doesn't match anything known
    (typo, stale frontend option, a picker label this table hasn't seen yet)
    always produces a note instead of falling through a bare dict .get(default).
    """
    raw = (raw or "").strip()
    if not raw:
        return DEFAULT_RISK_KEY, None

    if raw in CANONICAL_RISK_KEYS:
        return raw, None

    if raw in RISK_KEY_ALIASES:
        target = RISK_KEY_ALIASES[raw]
        return target, f"'{raw}' mapped to canonical risk profile '{target}' via RISK_KEY_ALIASES."

    lowered = raw.lower()
    for canon in CANONICAL_RISK_KEYS:
        if canon.lower() == lowered:
            return canon, f"'{raw}' matched canonical risk profile '{canon}' case-insensitively."
    for alias, target in RISK_KEY_ALIASES.items():
        if alias.lower() == lowered:
            return target, (
                f"'{raw}' matched risk-profile alias '{alias}' case-insensitively; mapped to '{target}'."
            )

    return DEFAULT_RISK_KEY, (
        f"'{raw}' does not match a known risk profile. Defaulted to "
        f"'{DEFAULT_RISK_KEY}'. Add it to RISK_KEY_ALIASES or CANONICAL_RISK_KEYS "
        "if this should be recognized."
    )


#: Canonical horizon strings understood by _forecast_window.
CANONICAL_HORIZONS: Tuple[str, ...] = ("Next 30 Days", "Quarterly Growth", "Year-End Outlook")

#: Synonyms for a horizon, in case a future request field spells these
#: differently than _forecast_window's exact three strings.
HORIZON_ALIASES: Dict[str, str] = {
    "30 Days": "Next 30 Days",
    "This Month": "Next 30 Days",
    "Monthly": "Next 30 Days",
    "Next Month": "Next 30 Days",
    "Quarterly": "Quarterly Growth",
    "Next Quarter": "Quarterly Growth",
    "3 Months": "Quarterly Growth",
    "Quarter": "Quarterly Growth",
    "Year End": "Year-End Outlook",
    "Full Year": "Year-End Outlook",
    "Annual": "Year-End Outlook",
    "Fiscal Year": "Year-End Outlook",
}


def _resolve_horizon(raw: Optional[str], default: str) -> Tuple[str, Optional[str]]:
    """
    Resolve an incoming horizon string to (canonical_horizon, note).

    Mirrors _resolve_target / _resolve_risk_key: an absent value silently uses
    the caller-supplied per-target default (nothing was wrong, nothing was
    sent). A present, non-matching value always produces a note rather than
    falling through to Next 30 Days unexplained - which is what
    _forecast_window's own internal else-branch used to do on its own.
    """
    raw = (raw or "").strip()
    if not raw:
        return default, None

    if raw in CANONICAL_HORIZONS:
        return raw, None

    if raw in HORIZON_ALIASES:
        target = HORIZON_ALIASES[raw]
        return target, f"'{raw}' mapped to canonical horizon '{target}' via HORIZON_ALIASES."

    lowered = raw.lower()
    for canon in CANONICAL_HORIZONS:
        if canon.lower() == lowered:
            return canon, f"'{raw}' matched canonical horizon '{canon}' case-insensitively."
    for alias, target in HORIZON_ALIASES.items():
        if alias.lower() == lowered:
            return target, (
                f"'{raw}' matched horizon alias '{alias}' case-insensitively; mapped to '{target}'."
            )

    return default, (
        f"'{raw}' does not match a known forecast horizon. Defaulted to '{default}'. "
        "Add it to HORIZON_ALIASES or CANONICAL_HORIZONS if this should be recognized."
    )


TARGET_TOOLS: Dict[str, str] = {
    "Revenue Growth": (
        "sales_forecast, sales_pipeline, sales_trend, period_comparison, "
        "variance_analysis, order_to_cash_cycle, top_products, purchase_vs_sales_margin"
    ),
    "Inventory Demand": (
        "sales_trend, top_products, inventory_dashboard_alerts, "
        "purchase_vs_sales_margin, period_comparison, variance_analysis"
    ),
    "Resource Capacity": (
        "sales_forecast, sales_trend, inventory_dashboard_alerts, "
        "order_to_cash_cycle, top_products, purchase_vs_sales_margin, variance_analysis"
    ),
}

TARGET_DEFAULT_HORIZON: Dict[str, str] = {
    "Revenue Growth": "Quarterly Growth",
    "Inventory Demand": "Next 30 Days",
    "Resource Capacity": "Quarterly Growth",
}


# ==========================================================================
# 3. SHARED CONTEXT BLOCK  (used by every target's prompt)
# ==========================================================================

def _common_context_block(
    *,
    today: _date,
    baseline: BaselineProfile,
    target_label: str,
    resolution_note: Optional[str],
    horizon_label: str,
    horizon_hint: str,
    window_start: _date,
    window_end: _date,
    window_days: int,
    window_selling_days: int,
    currency_hint: str,
    tools: str,
    extra_tags: str = "",
) -> str:
    baseline_line = (
        f"Historical Baseline Range: {baseline.start} to {baseline.end} "
        f"({baseline.months} months, ~{baseline.selling_days} selling days). "
        "Pass this range to every tool that accepts date filters."
        if baseline.is_bounded
        else "Historical Baseline Range: full available history (no date filter supplied). "
             "Leave tool date filters empty and report the actual span returned."
    )
    warning_block = (
        "\n".join(f"- {w}" for w in baseline.warnings) if baseline.warnings else "- None."
    )
    resolution_block = (
        f"<input_resolution>{resolution_note} The target, window, risk profile and "
        f"method fields below already reflect what was actually resolved - use them "
        "as authoritative.</input_resolution>\n"
        if resolution_note else ""
    )

    return f"""<request_context>
Today's Date: {today.isoformat()}
{baseline_line}
Baseline Warnings:
{warning_block}

<forecast_target>{target_label}</forecast_target>
{resolution_block}<forecast_window_start>{window_start.isoformat()}</forecast_window_start>
<forecast_window_end>{window_end.isoformat()}</forecast_window_end>
<forecast_window_label>{horizon_label}: {window_start.strftime('%b %d')} – {window_end.strftime('%b %d, %Y')}</forecast_window_label>
<forecast_window_calendar_days>{window_days}</forecast_window_calendar_days>
<forecast_window_selling_days>{window_selling_days}</forecast_window_selling_days>
<horizon_method>{horizon_hint}</horizon_method>
{currency_hint}
{extra_tags}Recommended Tools: {tools}
</request_context>"""


# ==========================================================================
# 4. TARGET A — REVENUE GROWTH
# ==========================================================================

BASE_STAGE_WEIGHTS: Dict[str, float] = {
    "Lead / Prospecting": 0.05,
    "Qualified / Discovery": 0.25,
    "Proposition / Proposal Sent": 0.55,
    "Negotiation / Contracting": 0.75,
    "Verbal Commit": 0.85,
    "Won / Closing": 0.90,
}
STAGE_WEIGHT_TABLE = "\n".join(
    f"   - {stage:<32} {int(w * 100):>3}%" for stage, w in BASE_STAGE_WEIGHTS.items()
)


@dataclass(frozen=True)
class RiskProfile:
    key: str
    strategy: str
    target_confidence: str
    confidence_anchor: int
    confidence_floor: int
    confidence_ceiling: int
    pipeline_multiplier: float
    slippage_factor: float
    headline_percentile: str
    buffer_note: str


RISK_PROFILES: Dict[str, RiskProfile] = {
    "Conservative (Safe)": RiskProfile(
        key="Conservative (Safe)",
        strategy=(
            "Downside-protected plan. Take the recency-weighted baseline, apply a "
            "10-15% downside buffer for sales slippage and supply constraints, and "
            "count only Negotiation-and-later pipeline at full stage weight. "
            "Earlier-stage pipeline is included at half its nominal weight."
        ),
        target_confidence="80-90%", confidence_anchor=85, confidence_floor=72, confidence_ceiling=90,
        pipeline_multiplier=0.85, slippage_factor=0.25,
        headline_percentile="P25 (bear-leaning, commit-grade number)",
        buffer_note="Apply -10% to -15% to the unconstrained gross forecast.",
    ),
    "Balanced (Standard)": RiskProfile(
        key="Balanced (Standard)",
        strategy=(
            "Most-likely plan. Recency-weighted historical baseline combined with "
            "stage-weighted pipeline conversion at nominal probabilities, adjusted "
            "for seasonality and observed close-rate history."
        ),
        target_confidence="70-80%", confidence_anchor=75, confidence_floor=60, confidence_ceiling=82,
        pipeline_multiplier=1.00, slippage_factor=0.15,
        headline_percentile="P50 (median / most-likely outcome)",
        buffer_note="No blanket buffer. Risk is expressed through the bear scenario.",
    ),
    "Aggressive (High Growth)": RiskProfile(
        key="Aggressive (High Growth)",
        strategy=(
            "Stretch plan. Assume near-full realisation of qualified pipeline plus a "
            "15-20% market momentum multiplier, contingent on momentum being "
            "empirically positive in the trend data. If momentum is negative, do NOT "
            "apply the multiplier - state that the stretch case is unsupported."
        ),
        target_confidence="55-65%", confidence_anchor=60, confidence_floor=45, confidence_ceiling=70,
        pipeline_multiplier=1.18, slippage_factor=0.08,
        headline_percentile="P75 (bull-leaning stretch target)",
        buffer_note="Momentum multiplier is conditional on positive observed growth.",
    ),
}

REVENUE_OUTPUT_SCHEMA_BLOCK = """```json
{
  "title": "3-6 word strategic forecast title",
  "value": "CUR X,XXX.XX — headline projected revenue for the window, with currency",
  "period": "Forecast window, e.g. 'Next 30 Days: Oct 01 – Oct 30, 2026'",
  "confidence": __CONFIDENCE_ANCHOR__,
  "currency": "ISO code observed in the source data",

  "insights": [
    "Baseline & momentum: recency-weighted run-rate, direction, and volatility.",
    "Pipeline conversion: open pipeline, stage-weighted expectation, coverage ratio.",
    "Margin & cash: projected gross margin flow-through and collected-cash view.",
    "Constraints & risk: fulfilment or concentration exposure quantified in currency."
  ],

  "scenarios": {
    "bear":  {"label": "Downside (P10)",  "value": "CUR X,XXX.XX", "probability": 10, "drivers": ["..."]},
    "base":  {"label": "Base case (P50)", "value": "CUR X,XXX.XX", "probability": 50, "drivers": ["..."]},
    "bull":  {"label": "Upside (P90)",    "value": "CUR X,XXX.XX", "probability": 90, "drivers": ["..."]}
  },

  "revenue_bridge": [
    {"label": "Normalised baseline run-rate", "amount": 0.00, "type": "opening", "basis": "tool + calc"},
    {"label": "Seasonal adjustment",          "amount": 0.00, "type": "adjust",  "basis": "..."},
    {"label": "Pipeline conversion (weighted)","amount": 0.00, "type": "add",    "basis": "..."},
    {"label": "Expansion / repeat uplift",    "amount": 0.00, "type": "add",     "basis": "..."},
    {"label": "Churn / non-recurring roll-off","amount": 0.00, "type": "deduct", "basis": "..."},
    {"label": "Price / mix effect",           "amount": 0.00, "type": "adjust",  "basis": "..."},
    {"label": "Capacity & stockout constraint","amount": 0.00, "type": "deduct", "basis": "..."},
    {"label": "Net forecast revenue",         "amount": 0.00, "type": "total",   "basis": "sum of above"}
  ],

  "metrics": [
    {"label": "Recency-weighted run-rate (monthly)", "value": "CUR X,XXX", "benchmark": "prior period CUR X,XXX", "status": "up | down | flat"},
    {"label": "Pipeline coverage ratio", "value": "X.Xx", "benchmark": "3.0x healthy", "status": "ok | watch | risk"},
    {"label": "Projected gross margin", "value": "XX.X%", "benchmark": "trailing XX.X%", "status": "up | down | flat"},
    {"label": "DSO / cash conversion", "value": "XX days", "benchmark": "-", "status": "ok | watch | risk"},
    {"label": "Revenue volatility (CV)", "value": "0.XX", "benchmark": "<0.35 stable", "status": "ok | watch | risk"}
  ],

  "assumptions": [
    {"assumption": "Stated assumption.", "basis": "Which tool/figure supports it.", "sensitivity": "If this moves 10%, forecast moves CUR X,XXX."}
  ],

  "risks": [
    {"risk": "Named risk.", "exposure": "CUR X,XXX", "likelihood": "high | medium | low", "mitigation": "Specific action."}
  ],

  "steps": [
    {"title": "Phase 1: Pipeline Acceleration & High-Probability Closing", "description": "...", "phase": 1, "window": "Days 1-30", "owner": "Sales / Revenue Ops", "value_at_stake": "CUR X,XXX", "target_metric": "..."},
    {"title": "Phase 2: Margin Protection & Discount Containment", "description": "...", "phase": 2, "window": "Days 30-60", "owner": "Commercial Finance", "value_at_stake": "CUR X,XXX", "target_metric": "..."},
    {"title": "Phase 3: Fulfilment, Inventory & Working Capital", "description": "...", "phase": 3, "window": "Days 60-90+", "owner": "Supply Chain / Treasury", "value_at_stake": "CUR X,XXX", "target_metric": "..."}
  ],

  "data_quality": {
    "baseline_months_observed": 0,
    "tools_returning_data": ["..."],
    "tools_returning_empty": ["..."],
    "seasonally_adjusted": false,
    "notes": "Anything that materially limits the reliability of this forecast."
  }
}
```"""


def _build_revenue_prompt(
    *, context_block: str, profile: RiskProfile, target_hint: str, window_selling_days: int,
    baseline: BaselineProfile,
) -> str:
    seasonality_rule = (
        "Baseline is long enough for a seasonal index. Compute it and apply it per month."
        if baseline.supports_seasonality
        else "Baseline is too short for a seasonal index. Do NOT invent seasonality. "
             "Forecast unadjusted and flag it as a risk."
    )
    return f"""{context_block}
<risk_profile>{profile.key}</risk_profile>
<risk_guidance>{profile.strategy}</risk_guidance>
<risk_buffer_rule>{profile.buffer_note}</risk_buffer_rule>
<pipeline_multiplier>{profile.pipeline_multiplier}</pipeline_multiplier>
<assumed_slippage_factor>{profile.slippage_factor}</assumed_slippage_factor>
<headline_scenario>{profile.headline_percentile}</headline_scenario>
<target_confidence_band>{profile.target_confidence}</target_confidence_band>
<confidence_anchor>{profile.confidence_anchor}</confidence_anchor>
{target_hint}

<role>
You are a Senior FP&A Director preparing a board-grade revenue and margin outlook.
You do not produce optimistic narratives; you produce a bridge, a scenario range,
and a calibrated confidence score, all traceable to retrieved data.
</role>

<instructions>
1. TOOL EXECUTION (SINGLE PARALLEL TURN):
   - In your initial turn, call all relevant data tools from the recommended list in parallel. Pass the baseline date range where accepted, and supply company_ids/tenant_ids from context.
   - Once tool results are returned, ALL DATA IS ACQUIRED. DO NOT CALL ANY MORE TOOLS.
   - DO NOT write any scratchpad math, commentary, or text analysis in the response. Perform calculations directly into the JSON field values.

2. ANALYTICAL METHOD - perform all steps below directly into the schema fields:

   A. BASELINE: build the monthly revenue series, normalise to revenue per selling
      day, compute T3M/T6M/T12M averages. Recency-weighted run-rate =
      0.50xT3M + 0.30xT6M + 0.20xT12M (renormalise weights if a window is missing).
      Compute CV (stdev/mean). State whether momentum is accelerating, flat or decaying.
   B. SEASONALITY: {seasonality_rule} Adjust for this window's selling-day count
      ({window_selling_days} days) vs the baseline's average selling days per month.
   C. PIPELINE: stage-weight open pipeline using these defaults, overriding with
      empirical win rates wherever the data supports it:
{STAGE_WEIGHT_TABLE}
      Age decay: 1.5x average cycle length -> -30%; past close date -> -50%.
      Reduce in-period value by the assumed slippage factor, then apply the
      pipeline multiplier. Pipeline coverage ratio = open pipeline / new-business
      needed; below 3.0x is a coverage risk, below 2.0x is a confidence deduction.
      If top 3 opportunities exceed 40% of weighted pipeline, name the concentration risk.
   D. REVENUE BRIDGE - populate every line, they must sum to the total:
      baseline -> seasonal adjustment -> pipeline conversion -> expansion uplift
      -> churn/non-recurring roll-off -> price/mix -> capacity constraint -> net forecast.
      Keep a zero line rather than dropping it.
   E. MARGIN: blended GM% from purchase_vs_sales_margin; decompose price/volume/mix
      effects; quantify discount leakage in GM points; gross profit = net revenue x GM%.
   F. CASH: from order_to_cash_cycle, estimate collected cash separately from booked
      revenue using DSO. Quantify capacity constraint (stockouts/backorders on top
      revenue SKUs) in currency - this becomes the bridge's constraint line.
   G. SCENARIOS: bear(P10)/base(P50)/bull(P90); PERT expected value =
      (bear+4*base+bull)/6. Bear must be driven by named specific downside events.
      Headline "value" = {profile.headline_percentile}. Sanity gate: bear<base<bull.
   H. CONFIDENCE: start at {profile.confidence_anchor}, deduct - thin baseline
      (<{MIN_BASELINE_MONTHS}mo) -20, CV>0.35 -10, no seasonality
      (<{SEASONALITY_MIN_MONTHS}mo) -5, top-3 concentration>40% -8, active stockouts
      on top-5 SKUs -7, coverage<2.0x -10, each empty tool -5. Clamp into
      [{profile.confidence_floor}, {profile.confidence_ceiling}] unless the
      data-sufficiency gate below fires. Show the arithmetic in data_quality.notes.

3. DATA-SUFFICIENCY GATE (overrides everything above): if both historical sales
   AND pipeline are empty, set confidence<=30, title/value = "Insufficient
   Historical Baseline", zero the bridge and scenarios, state exactly what's
   missing in insights. Never fabricate a revenue history, deal, or customer.
   If only one is empty, force confidence<=50 and name the gap as the leading risk.

4. DISCIPLINE: every figure traces to a tool result or arithmetic on one; label
   derived vs estimated; use the currency present in source data; round to 2dp;
   reconcile before emitting (bridge sums to total, total sits inside the
   scenario range, gross profit = revenue x GM%, confidence = anchor minus
   stated deductions).

5. EXECUTION MILESTONES - exactly 3 phases, each with a currency amount at stake
   drawn from the bridge, an owner function, and a measurable target metric:
   Phase 1 (Days 1-30) pipeline conversion; Phase 2 (Days 30-60) margin
   preservation; Phase 3 (Days 60-90+) operational/working-capital alignment.
   Generic advice with no number attached is a failure.

6. STRICT JSON FORMAT:
   - Output EXACTLY one valid JSON object enclosed within a single ```json ``` block.
   - STRICT REQUIREMENT: Output ZERO text, preamble, or conversational words outside the ```json ``` block.
</instructions>

<output_schema>
{REVENUE_OUTPUT_SCHEMA_BLOCK.replace("__CONFIDENCE_ANCHOR__", str(profile.confidence_anchor))}
</output_schema>"""


# ==========================================================================
# 5. TARGET B — INVENTORY DEMAND
# ==========================================================================

@dataclass(frozen=True)
class InventoryRiskProfile:
    key: str
    strategy: str
    target_confidence: str
    confidence_anchor: int
    confidence_floor: int
    confidence_ceiling: int
    service_level_target: str
    safety_stock_note: str


INVENTORY_RISK_PROFILES: Dict[str, InventoryRiskProfile] = {
    "Conservative (Safe)": InventoryRiskProfile(
        key="Conservative (Safe)",
        strategy=(
            "Protect against stockouts even at the cost of higher carrying cost. "
            "Order early, hold generous safety stock, and treat demand spikes as "
            "the base case for top-velocity SKUs."
        ),
        target_confidence="80-90%", confidence_anchor=85, confidence_floor=72, confidence_ceiling=90,
        service_level_target="97-99%",
        safety_stock_note="Size safety stock for roughly a 2-2.3 standard-deviation demand buffer over lead time.",
    ),
    "Balanced (Standard)": InventoryRiskProfile(
        key="Balanced (Standard)",
        strategy=(
            "Standard service-level target balancing stockout risk against carrying "
            "cost. Reorder points sized to typical demand variability, not worst case."
        ),
        target_confidence="70-80%", confidence_anchor=75, confidence_floor=60, confidence_ceiling=82,
        service_level_target="90-95%",
        safety_stock_note="Size safety stock for roughly a 1.3-1.6 standard-deviation demand buffer over lead time.",
    ),
    "Aggressive (High Growth)": InventoryRiskProfile(
        key="Aggressive (High Growth)",
        strategy=(
            "Lean inventory: minimize capital tied up and carrying cost, accept "
            "materially higher stockout risk on lower-velocity SKUs to free up cash "
            "for growth elsewhere. Do not apply this leanness to top-velocity or "
            "single-source SKUs without flagging the risk explicitly."
        ),
        target_confidence="55-65%", confidence_anchor=60, confidence_floor=45, confidence_ceiling=70,
        service_level_target="80-88%",
        safety_stock_note="Size safety stock for roughly a 0.8-1.0 standard-deviation demand buffer over lead time.",
    ),
}

INVENTORY_OUTPUT_SCHEMA_BLOCK = """```json
{
  "title": "3-6 word inventory forecast title",
  "value": "CUR X,XXX.XX — total recommended replenishment spend for the window, with currency",
  "period": "Forecast window, e.g. 'Next 30 Days: Oct 01 – Oct 30, 2026'",
  "confidence": __CONFIDENCE_ANCHOR__,
  "currency": "ISO code observed in the source data",

  "insights": [
    "Demand baseline: recency-weighted unit demand, direction, and volatility.",
    "Stockout & coverage risk: which SKUs are at risk and the revenue exposure.",
    "Capital & carrying cost: cash tied up in safety stock and current inventory.",
    "Concentration risk: SKU or supplier dependency exposure."
  ],

  "demand_scenarios": {
    "bear":  {"label": "Low demand (P10)",  "value": "X,XXX units", "probability": 10, "drivers": ["..."]},
    "base":  {"label": "Expected demand (P50)", "value": "X,XXX units", "probability": 50, "drivers": ["..."]},
    "bull":  {"label": "High demand (P90)", "value": "X,XXX units", "probability": 90, "drivers": ["..."]}
  },

  "inventory_position": {
    "opening_stock_value": 0.00,
    "projected_demand_value": 0.00,
    "safety_stock_requirement_value": 0.00,
    "recommended_replenishment_value": 0.00,
    "capital_tied_up_value": 0.00
  },

  "reorder_recommendations": [
    {
      "sku": "Item name/code from source data",
      "current_stock_units": 0,
      "daily_demand_rate_units": 0.0,
      "lead_time_days": 0,
      "lead_time_basis": "observed | estimated - state which",
      "reorder_point_units": 0,
      "recommended_order_units": 0,
      "recommended_order_value": 0.00,
      "stockout_risk_days": 0,
      "abc_class": "A | B | C"
    }
  ],

  "metrics": [
    {"label": "Inventory turnover ratio", "value": "X.Xx", "benchmark": "-", "status": "ok | watch | risk"},
    {"label": "Days of supply (top SKUs)", "value": "XX days", "benchmark": "-", "status": "ok | watch | risk"},
    {"label": "Stockout exposure", "value": "CUR X,XXX", "benchmark": "-", "status": "ok | watch | risk"},
    {"label": "Demand volatility (CV)", "value": "0.XX", "benchmark": "<0.35 stable", "status": "ok | watch | risk"},
    {"label": "Service level achieved (est.)", "value": "XX%", "benchmark": "target __SERVICE_LEVEL__", "status": "ok | watch | risk"}
  ],

  "risks": [
    {"risk": "Named risk.", "exposure": "CUR X,XXX", "likelihood": "high | medium | low", "mitigation": "Specific action."}
  ],

  "steps": [
    {"title": "Phase 1: Immediate Reorder on At-Risk SKUs", "description": "...", "phase": 1, "window": "Days 1-30", "owner": "Procurement / Supply Chain", "value_at_stake": "CUR X,XXX", "target_metric": "..."},
    {"title": "Phase 2: Safety Stock & Service-Level Policy Tuning", "description": "...", "phase": 2, "window": "Days 30-60", "owner": "Inventory Planning", "value_at_stake": "CUR X,XXX", "target_metric": "..."},
    {"title": "Phase 3: ABC-Based Inventory Investment Reallocation", "description": "...", "phase": 3, "window": "Days 60-90+", "owner": "Operations / Finance", "value_at_stake": "CUR X,XXX", "target_metric": "..."}
  ],

  "data_quality": {
    "baseline_months_observed": 0,
    "tools_returning_data": ["..."],
    "tools_returning_empty": ["..."],
    "seasonally_adjusted": false,
    "lead_time_data_available": false,
    "notes": "Anything that materially limits the reliability of this forecast."
  }
}
```"""


def _build_inventory_prompt(
    *, context_block: str, profile: InventoryRiskProfile, baseline: BaselineProfile,
    window_selling_days: int,
) -> str:
    seasonality_rule = (
        "Baseline is long enough for a seasonal index. Compute it and apply it per SKU."
        if baseline.supports_seasonality
        else "Baseline is too short for a seasonal index. Do NOT invent seasonality. "
             "Forecast unadjusted and flag it as a risk."
    )
    schema = INVENTORY_OUTPUT_SCHEMA_BLOCK.replace(
        "__CONFIDENCE_ANCHOR__", str(profile.confidence_anchor)
    ).replace("__SERVICE_LEVEL__", profile.service_level_target)

    return f"""{context_block}
<risk_profile>{profile.key}</risk_profile>
<risk_guidance>{profile.strategy}</risk_guidance>
<service_level_target>{profile.service_level_target}</service_level_target>
<safety_stock_calibration>{profile.safety_stock_note}</safety_stock_calibration>
<target_confidence_band>{profile.target_confidence}</target_confidence_band>
<confidence_anchor>{profile.confidence_anchor}</confidence_anchor>

<role>
You are a Senior Inventory Planning Analyst producing a demand forecast and
replenishment plan. Your output drives real purchase orders, so every reorder
recommendation must trace to observed demand and observed (or clearly flagged
as estimated) lead time - never a plausible-sounding guess presented as fact.
</role>

<instructions>
1. TOOL EXECUTION (SINGLE PARALLEL TURN):
   - In your initial turn, call the recommended tools in parallel; pass the baseline date range where accepted.
   - Once tool results are returned, ALL DATA IS ACQUIRED. DO NOT CALL ANY MORE TOOLS.
   - DO NOT write scratchpad math, commentary, or text analysis in the response.

2. ANALYTICAL METHOD - compute directly into the schema fields:

   A. DEMAND BASELINE: build per-SKU unit-demand series from sales_trend and
      top_products. Recency-weighted demand rate = 0.50xT3M + 0.30xT6M + 0.20xT12M
      (renormalise if a window is missing). Compute CV per SKU. ABC-classify by
      revenue contribution (A = top ~80% of revenue, B = next ~15%, C = remainder).
   B. SEASONALITY: {seasonality_rule} Normalise to demand per selling day; this
      window has {window_selling_days} selling days.
   C. LEAD TIME: derive supplier lead time from purchase-side data if the tools
      expose it. If not directly available, ESTIMATE from typical replenishment
      cadence observed in the data and label lead_time_basis "estimated" on every
      affected SKU - never silently treat an estimate as observed.
   D. SAFETY STOCK & REORDER POINT: target service level {profile.service_level_target}.
      {profile.safety_stock_note} Reorder point = (daily demand rate x lead time
      days) + safety stock. Recommended order quantity should bring projected
      coverage through the forecast window plus one lead-time cycle.
   E. STOCKOUT & CAPITAL RISK: from inventory_dashboard_alerts, identify current
      stock, backorders and active stockouts. Quantify revenue at risk from
      projected stockouts on top-velocity SKUs in currency. Quantify capital tied
      up in current inventory and in the recommended safety stock.
   F. CONCENTRATION: if 3 or fewer SKUs represent over 50% of projected demand
      value, name it as a concentration risk - a single supply disruption on one
      of them is a material exposure.
   G. SCENARIOS: bear(P10)/base(P50)/bull(P90) demand in units. PERT expected =
      (bear+4*base+bull)/6.
   H. CONFIDENCE: start at {profile.confidence_anchor}, deduct - thin baseline
      (<{MIN_BASELINE_MONTHS}mo) -20, demand CV>0.35 -10, no seasonality
      (<{SEASONALITY_MIN_MONTHS}mo) -5, top-3 SKU concentration>50% -8, active
      stockouts on top-revenue SKUs -7, lead time had to be estimated rather than
      observed -10, each empty tool -5. Clamp into
      [{profile.confidence_floor}, {profile.confidence_ceiling}] unless the
      data-sufficiency gate fires. Show the arithmetic in data_quality.notes.

3. DATA-SUFFICIENCY GATE: if both sales_trend/top_products AND
   inventory_dashboard_alerts return empty, set confidence<=30, title/value =
   "Insufficient Inventory Data", zero the reorder recommendations, state exactly
   what's missing. Never fabricate a SKU, a stock level, or a lead time.

4. DISCIPLINE: every figure traces to a tool result or arithmetic on one; label
   observed vs estimated explicitly (especially lead time); use the currency
   present in source data; never invent a SKU name or code.

5. EXECUTION MILESTONES - exactly 3 phases, each with a currency amount at stake
   and a measurable target metric: Phase 1 (Days 1-30) immediate reorder on
   at-risk SKUs; Phase 2 (Days 30-60) safety stock / service-level policy tuning;
   Phase 3 (Days 60-90+) ABC-based inventory investment reallocation.

6. STRICT JSON FORMAT:
   - Output EXACTLY one valid JSON object enclosed within a single ```json ``` block.
   - STRICT REQUIREMENT: Output ZERO text, preamble, or conversational words outside the ```json ``` block.
</instructions>

<output_schema>
{schema}
</output_schema>"""


# ==========================================================================
# 6. TARGET C — RESOURCE CAPACITY
# ==========================================================================

@dataclass(frozen=True)
class CapacityRiskProfile:
    key: str
    strategy: str
    target_confidence: str
    confidence_anchor: int
    confidence_floor: int
    confidence_ceiling: int
    utilization_buffer: str


CAPACITY_RISK_PROFILES: Dict[str, CapacityRiskProfile] = {
    "Conservative (Safe)": CapacityRiskProfile(
        key="Conservative (Safe)",
        strategy=(
            "Retain a large capacity buffer across inventory, working capital and "
            "fulfilment throughput. Treat 70-80% utilization as the practical ceiling."
        ),
        target_confidence="80-90%", confidence_anchor=85, confidence_floor=72, confidence_ceiling=90,
        utilization_buffer="30-40% headroom retained on every dimension",
    ),
    "Balanced (Standard)": CapacityRiskProfile(
        key="Balanced (Standard)",
        strategy=(
            "Standard operating buffer. Treat 80-85% utilization as the practical "
            "ceiling before a dimension is flagged as binding."
        ),
        target_confidence="70-80%", confidence_anchor=75, confidence_floor=60, confidence_ceiling=82,
        utilization_buffer="15-20% headroom retained",
    ),
    "Aggressive (High Growth)": CapacityRiskProfile(
        key="Aggressive (High Growth)",
        strategy=(
            "Run close to full utilization to maximize throughput; accept a higher "
            "chance of hitting a binding constraint mid-window in exchange for lower "
            "idle capacity cost."
        ),
        target_confidence="55-65%", confidence_anchor=60, confidence_floor=45, confidence_ceiling=70,
        utilization_buffer="5-10% headroom retained",
    ),
}

CAPACITY_OUTPUT_SCHEMA_BLOCK = """```json
{
  "title": "3-6 word capacity forecast title",
  "value": "CUR X,XXX.XX or XX% — headline capacity gap or surplus for the window, with currency or percent",
  "period": "Forecast window, e.g. 'Q4 2026: Oct 01 – Dec 31, 2026'",
  "confidence": __CONFIDENCE_ANCHOR__,
  "currency": "ISO code observed in the source data",

  "insights": [
    "Demand trajectory: projected order/sales volume driving capacity need.",
    "Binding constraint: which capacity dimension limits growth first and why.",
    "Utilization outlook: current vs projected utilization on each dimension.",
    "Risk: what happens if the binding constraint is not addressed."
  ],

  "capacity_gap": [
    {
      "dimension": "inventory_capacity | working_capital_capacity | fulfilment_throughput",
      "required": "value or description of what the projected demand needs",
      "available": "value or description of what is currently available",
      "gap": "CUR X,XXX or XX% — shortfall or surplus",
      "utilization_pct": 0,
      "status": "ok | watch | risk"
    }
  ],

  "binding_constraint": {
    "dimension": "Which of the three dimensions binds first",
    "reasoning": "Why this one binds before the others, grounded in the gap analysis above",
    "days_to_bind": "Estimated days into the window before this constraint is hit, or 'already binding'"
  },

  "demand_scenarios": {
    "bear":  {"label": "Low demand (P10)",  "value": "description", "probability": 10, "drivers": ["..."]},
    "base":  {"label": "Expected demand (P50)", "value": "description", "probability": 50, "drivers": ["..."]},
    "bull":  {"label": "High demand (P90)", "value": "description", "probability": 90, "drivers": ["..."]}
  },

  "metrics": [
    {"label": "Order-to-cash cycle", "value": "XX days", "benchmark": "-", "status": "ok | watch | risk"},
    {"label": "Days of inventory supply", "value": "XX days", "benchmark": "-", "status": "ok | watch | risk"},
    {"label": "Current utilization (binding dimension)", "value": "XX%", "benchmark": "target buffer __UTIL_BUFFER__", "status": "ok | watch | risk"},
    {"label": "Projected utilization, end of window", "value": "XX%", "benchmark": "-", "status": "ok | watch | risk"}
  ],

  "risks": [
    {"risk": "Named risk.", "exposure": "CUR X,XXX", "likelihood": "high | medium | low", "mitigation": "Specific action."}
  ],

  "steps": [
    {"title": "Phase 1: Immediate Relief on Binding Constraint", "description": "...", "phase": 1, "window": "Days 1-30", "owner": "Operations", "value_at_stake": "CUR X,XXX", "target_metric": "..."},
    {"title": "Phase 2: Working Capital / Supplier Terms Adjustment", "description": "...", "phase": 2, "window": "Days 30-60", "owner": "Treasury / Procurement", "value_at_stake": "CUR X,XXX", "target_metric": "..."},
    {"title": "Phase 3: Structural Capacity Investment", "description": "...", "phase": 3, "window": "Days 60-90+", "owner": "Operations / Finance", "value_at_stake": "CUR X,XXX", "target_metric": "..."}
  ],

  "data_quality": {
    "baseline_months_observed": 0,
    "tools_returning_data": ["..."],
    "tools_returning_empty": ["..."],
    "seasonally_adjusted": false,
    "notes": "Anything that materially limits the reliability of this forecast, including which capacity dimensions could not be assessed."
  }
}
```"""


def _build_capacity_prompt(
    *, context_block: str, profile: CapacityRiskProfile, baseline: BaselineProfile,
) -> str:
    seasonality_rule = (
        "Baseline is long enough for a seasonal index on demand. Compute and apply it."
        if baseline.supports_seasonality
        else "Baseline is too short for a seasonal index. Do NOT invent seasonality."
    )
    schema = CAPACITY_OUTPUT_SCHEMA_BLOCK.replace(
        "__CONFIDENCE_ANCHOR__", str(profile.confidence_anchor)
    ).replace("__UTIL_BUFFER__", profile.utilization_buffer)

    return f"""{context_block}
<risk_profile>{profile.key}</risk_profile>
<risk_guidance>{profile.strategy}</risk_guidance>
<utilization_buffer_target>{profile.utilization_buffer}</utilization_buffer_target>
<target_confidence_band>{profile.target_confidence}</target_confidence_band>
<confidence_anchor>{profile.confidence_anchor}</confidence_anchor>

<scope_of_this_analysis>
This tool surface exposes inventory, cash-conversion and order-throughput data -
no headcount, staffing, or production-line capacity tool is connected. "Resource
Capacity" is therefore assessed across exactly three OPERATIONAL dimensions:
  1. Inventory capacity - can available stock plus incoming purchases support
     projected demand.
  2. Working capital capacity - can the cash-conversion cycle finance the working
     capital projected growth requires.
  3. Fulfilment throughput - using order-to-cash cycle time as a proxy for how
     many orders can be processed in the window.
Do NOT report a headcount, staffing count, or labor-hours figure - there is no
tool access to that data, and inventing one would be a fabrication. If the person
plainly wants staffing/headcount capacity rather than this operational view, say
so explicitly in insights and data_quality.notes rather than guessing a number.
</scope_of_this_analysis>

<role>
You are a Senior Operations/FP&A Analyst assessing whether the business can
operationally support its projected demand over the forecast window, and which
constraint binds first if not.
</role>

<instructions>
1. TOOL EXECUTION (SINGLE PARALLEL TURN):
   - In your initial turn, call the recommended tools in parallel; pass the baseline date range where accepted.
   - Once tool results are returned, ALL DATA IS ACQUIRED. DO NOT CALL ANY MORE TOOLS.
   - DO NOT write scratchpad math, commentary, or text analysis in the response.

2. ANALYTICAL METHOD - compute directly into the schema fields:

   A. DEMAND TRAJECTORY: build the projected order/sales volume for the window
      from sales_forecast/sales_trend using a recency-weighted run-rate
      (0.50xT3M + 0.30xT6M + 0.20xT12M, renormalised if a window is missing).
   B. SEASONALITY: {seasonality_rule}
   C. INVENTORY CAPACITY: from inventory_dashboard_alerts and top_products,
      compare available stock plus any incoming purchases against projected
      demand for top-velocity SKUs. Express as a utilization percentage and a
      currency gap or surplus.
   D. WORKING CAPITAL CAPACITY: from order_to_cash_cycle and
      purchase_vs_sales_margin, compute the cash-conversion cycle (DSO+DIO-DPO)
      and the incremental working capital projected growth would absorb. Compare
      against what the data shows is currently available/financeable.
   E. FULFILMENT THROUGHPUT: use order-to-cash cycle time as a proxy for orders
      processable per period; compare against the volume the demand trajectory implies.
   F. BINDING CONSTRAINT: of the three dimensions, identify which one reaches its
      utilization buffer target ({profile.utilization_buffer}) first, and roughly
      how many days into the window that happens. State the reasoning, not just
      the conclusion.
   G. SCENARIOS: bear(P10)/base(P50)/bull(P90) demand against the SAME fixed
      capacity, so the scenarios show how the gap changes with demand, not with
      capacity.
   H. CONFIDENCE: start at {profile.confidence_anchor}, deduct - thin baseline
      (<{MIN_BASELINE_MONTHS}mo) -20, no seasonality (<{SEASONALITY_MIN_MONTHS}mo)
      -5, any of the three dimensions has no usable data -8 each, a dimension is
      already observed above 90% utilization (binding imminent, raises estimation
      uncertainty) -10, each empty tool -5. Clamp into
      [{profile.confidence_floor}, {profile.confidence_ceiling}] unless the
      data-sufficiency gate fires. Show the arithmetic in data_quality.notes.

3. DATA-SUFFICIENCY GATE: if all three dimensions return no usable data, set
   confidence<=30, title/value = "Insufficient Capacity Data", leave
   capacity_gap and binding_constraint empty/null, state exactly what's missing.
   If only one or two dimensions have data, proceed with those, force
   confidence<=55, and name the unassessed dimension(s) as a named gap in
   data_quality.notes - do not silently omit them.

4. DISCIPLINE: every figure traces to a tool result or arithmetic on one; label
   derived vs estimated; use the currency present in source data; never invent a
   headcount, staffing, or labor-hours number.

5. EXECUTION MILESTONES - exactly 3 phases tied to the binding constraint: Phase 1
   (Days 1-30) immediate relief on the binding dimension; Phase 2 (Days 30-60)
   working capital or supplier-terms adjustment; Phase 3 (Days 60-90+) structural
   capacity investment.

6. STRICT JSON FORMAT:
   - Output EXACTLY one valid JSON object enclosed within a single ```json ``` block.
   - STRICT REQUIREMENT: Output ZERO text, preamble, or conversational words outside the ```json ``` block.
</instructions>

<output_schema>
{schema}
</output_schema>"""


# ==========================================================================
# 7. CUSTOM / UNMAPPED TARGET  (free-text fallback)
# ==========================================================================

def _build_custom_prompt(*, context_block: str, profile: RiskProfile, raw_request: str) -> str:
    """
    Best-effort path for free text typed into the "custom request" box that
    doesn't match a known target. Reuses the revenue schema as the most general
    financial-forecast structure, but requires the model to state plainly what
    it understood the request to mean before computing anything.
    """
    return f"""{context_block}
<custom_request_text>{raw_request}</custom_request_text>
<risk_profile>{profile.key}</risk_profile>
<risk_guidance>{profile.strategy}</risk_guidance>
<confidence_anchor>{profile.confidence_anchor}</confidence_anchor>

<role>
You are a Senior FP&A Analyst handling a free-text forecast request that does not
match one of this system's named forecast targets (Revenue Growth, Inventory
Demand, Resource Capacity).
</role>

<instructions>
1. INTERPRET FIRST: state in one sentence, as the first item of "insights", what
   you understood <custom_request_text> to be asking for. If it clearly matches
   one of the three named targets under different wording, say so and analyze it
   that way. If it's genuinely something else, proceed as a general financial
   forecast using whichever recommended tools are relevant.
2. In your initial turn, run the recommended tools relevant to your interpretation in parallel.
   Once tool results are returned, ALL DATA IS ACQUIRED. DO NOT CALL ANY MORE TOOLS.
   DO NOT write scratchpad math, commentary, or text analysis in the response.
3. Ground every figure in retrieved data or arithmetic on it; label estimates;
   use the currency present in the source data.
4. If the request cannot be answered from the tools available (e.g. it asks for
   data this system does not track), say so plainly in insights and
   data_quality.notes rather than fabricating a number, set confidence<=30, and
   title/value = "Unsupported Forecast Request".
5. Populate the schema below as best fits - a revenue_bridge line can be zero or
   renamed via its "label" field if the request isn't revenue-shaped, but keep
   every top-level key present.
6. STRICT JSON FORMAT:
   - Output EXACTLY one valid JSON object enclosed within a single ```json ``` block.
   - STRICT REQUIREMENT: Output ZERO text, preamble, or conversational words outside the ```json ``` block.
</instructions>

<output_schema>
{REVENUE_OUTPUT_SCHEMA_BLOCK.replace("__CONFIDENCE_ANCHOR__", str(profile.confidence_anchor))}
</output_schema>"""


# ==========================================================================
# 8. RESPONSE GUARD  (generic across all targets)
# ==========================================================================

REVENUE_REQUIRED_KEYS: Dict[str, Any] = {
    "title": "Revenue Forecast", "value": "Not available", "period": "", "confidence": 50,
    "currency": "", "insights": list, "scenarios": dict, "revenue_bridge": list,
    "metrics": list, "assumptions": list, "risks": list, "steps": list, "data_quality": dict,
}
INVENTORY_REQUIRED_KEYS: Dict[str, Any] = {
    "title": "Inventory Forecast", "value": "Not available", "period": "", "confidence": 50,
    "currency": "", "insights": list, "demand_scenarios": dict, "inventory_position": dict,
    "reorder_recommendations": list, "metrics": list, "risks": list, "steps": list, "data_quality": dict,
}
CAPACITY_REQUIRED_KEYS: Dict[str, Any] = {
    "title": "Capacity Forecast", "value": "Not available", "period": "", "confidence": 50,
    "currency": "", "insights": list, "capacity_gap": list, "binding_constraint": dict,
    "demand_scenarios": dict, "metrics": list, "risks": list, "steps": list, "data_quality": dict,
}


def _coerce_confidence(raw: Any, profile: Any) -> int:
    """
    Clamp a model-reported confidence into the risk profile's band - EXCEPT
    when the model has legitimately gone below the floor. A below-floor value
    only ever gets there because a data-sufficiency gate told the model to put
    it there (full gate: <=30; partial gates: <=50 / <=55 depending on target).
    Bouncing that back up to the floor silently defeats exactly the signal
    those gates exist to send - so floor only clamps upward drift, never
    downward, and the ceiling still applies unconditionally either way.
    """
    try:
        value = int(round(float(raw)))
    except (TypeError, ValueError):
        value = profile.confidence_anchor
    value = max(0, min(100, value))
    if value < profile.confidence_floor:
        return value
    return min(profile.confidence_ceiling, value)


def _normalise_steps(steps: Any) -> List[Dict[str, Any]]:
    fallback = [
        {"title": "Phase 1", "description": "Not generated.", "phase": 1, "window": "Days 1-30"},
        {"title": "Phase 2", "description": "Not generated.", "phase": 2, "window": "Days 30-60"},
        {"title": "Phase 3", "description": "Not generated.", "phase": 3, "window": "Days 60-90+"},
    ]
    if not isinstance(steps, list) or not steps:
        return fallback
    cleaned: List[Dict[str, Any]] = []
    for idx, step in enumerate(steps[:3], start=1):
        if not isinstance(step, dict):
            continue
        cleaned.append({
            "title": str(step.get("title") or f"Phase {idx}"),
            "description": str(step.get("description") or ""),
            "phase": step.get("phase", idx),
            "window": step.get("window", ""),
            "owner": step.get("owner", ""),
            "value_at_stake": step.get("value_at_stake", ""),
            "target_metric": step.get("target_metric", ""),
        })
    return cleaned or fallback


def _guard_payload(
    payload: Any,
    *,
    required_keys: Optional[Dict[str, Any]] = None,
    profile: Any,
    period_label: str,
    baseline: BaselineProfile,
    resolution_note: Optional[str] = None,
) -> Dict[str, Any]:
    """Fill gaps, coerce types, and stamp server-known facts. Works for any target
    because required_keys is passed in rather than hardcoded."""
    if required_keys is None:
        required_keys = REVENUE_REQUIRED_KEYS

    if not isinstance(payload, dict):
        payload = {}
    out: Dict[str, Any] = dict(payload)

    for key, default in required_keys.items():
        if key not in out or out[key] is None:
            out[key] = default() if callable(default) else default
        elif callable(default) and not isinstance(out[key], default):
            out[key] = default()

    out["confidence"] = _coerce_confidence(out.get("confidence"), profile)
    if "steps" in required_keys:
        out["steps"] = _normalise_steps(out.get("steps"))
    if "insights" in required_keys:
        out["insights"] = [str(i) for i in out.get("insights", []) if i][:6] or [
            "No insights were generated from the available data."
        ]
    if not str(out.get("period") or "").strip():
        out["period"] = period_label

    if "data_quality" in required_keys:
        dq = out["data_quality"] if isinstance(out.get("data_quality"), dict) else {}
        dq.setdefault("baseline_months_observed", baseline.months or 0)
        dq.setdefault("seasonally_adjusted", baseline.supports_seasonality)
        dq.setdefault("tools_returning_data", [])
        dq.setdefault("tools_returning_empty", [])
        dq.setdefault("notes", "")
        if resolution_note:
            dq["notes"] = (str(dq.get("notes") or "") + " | " + resolution_note).strip(" |")
        out["data_quality"] = dq

    out["risk_profile"] = getattr(profile, "key", "")
    if hasattr(profile, "headline_percentile"):
        out["methodology"] = profile.headline_percentile
    return out


# ==========================================================================
# 9. RUNNER & ENDPOINT INTEGRATION
# ==========================================================================

async def execute_cfo_forecast(
    *,
    req: Any,
    primary_tenant_id: Optional[str] = None,
    resolved_tenant_ids: Optional[List[str]] = None,
    resolved_company_ids: Optional[List[int]] = None,
    run_node_fn: Optional[Callable[..., Any]] = None,
) -> Dict[str, Any]:
    """Coordinates multi-domain forecast dispatch, execution, and payload guarding."""
    if run_node_fn is None:
        from doova_one_view.api.agent.routes import _run_structured_node
        run_node_fn = _run_structured_node

    # Prefer a future-renamed field if the request model ever grows one; fall
    # back to `scope`, which is the actual wire contract today even though the
    # frontend is really sending a forecast TARGET through it, not a scope.
    target_raw = (getattr(req, "forecast_target", None) or getattr(req, "scope", None) or "").strip() or "Revenue Growth"
    target_key, horizon_override, target_note = _resolve_target(target_raw)

    # Same never-silent treatment for risk_profile - a bare dict .get(default)
    # here used to swallow anything that wasn't one of the three exact strings.
    risk_raw = (getattr(req, "risk_profile", None) or "").strip()
    risk_key, risk_note = _resolve_risk_key(risk_raw)

    session_id = getattr(req, "session_id", None) or str(uuid.uuid4())
    today = _date.today()

    fy_end_month = getattr(req, "fiscal_year_end_month", 12) or 12
    currency = (getattr(req, "currency", None) or "").strip()
    target_revenue = getattr(req, "target_value", None) or getattr(req, "target_revenue", None)

    # And for horizon: only meaningful today via the legacy-scope override, but
    # resolved the same way in case a dedicated horizon field ever lands on the
    # request model with a value this registry hasn't seen yet.
    horizon_raw = (
        getattr(req, "time_horizon", None)
        or getattr(req, "horizon", None)
        or getattr(req, "time_scope", None)
        or horizon_override
    )
    horizon, horizon_note = _resolve_horizon(
        horizon_raw, default=TARGET_DEFAULT_HORIZON.get(target_key, "Next 30 Days")
    )

    # Every non-silent resolution across all three inputs gets logged
    # individually (so a spike in one specific unmapped value is traceable)
    # and combined into one note surfaced in the response.
    resolution_notes = [n for n in (target_note, risk_note, horizon_note) if n]
    for note in resolution_notes:
        log_error("run_forecast.input_resolution", RuntimeError(note))
    resolution_note = " | ".join(resolution_notes) or None

    window_start, window_end, horizon_label, horizon_hint = _forecast_window(horizon, today, fy_end_month)
    window_days = (window_end - window_start).days + 1
    window_selling_days = _selling_days(window_start, window_end)

    baseline = _profile_baseline(
        _parse_date(getattr(req, "start_date", None)),
        _parse_date(getattr(req, "end_date", None)),
    )

    currency_hint = (
        f"<reporting_currency>{currency}</reporting_currency>"
        if currency
        else "<reporting_currency>Detect from the tool data and state it explicitly. "
             "Do not mix or convert currencies.</reporting_currency>"
    )

    tools = TARGET_TOOLS.get(target_key, TARGET_TOOLS["Revenue Growth"])
    context_block = _common_context_block(
        today=today, baseline=baseline, target_label=target_key, resolution_note=resolution_note,
        horizon_label=horizon_label, horizon_hint=horizon_hint,
        window_start=window_start, window_end=window_end,
        window_days=window_days, window_selling_days=window_selling_days,
        currency_hint=currency_hint, tools=tools,
    )

    period_label = f"{horizon_label}: {window_start.strftime('%b %d')} – {window_end.strftime('%b %d, %Y')}"
    user_label = f"Forecast: {target_key} ({risk_key})"
    session_tenant_id = primary_tenant_id or "default"

    # Dispatch to the target-specific prompt, schema, and risk profile.
    if target_key == "Revenue Growth":
        profile = RISK_PROFILES.get(risk_key, RISK_PROFILES[DEFAULT_RISK_KEY])
        target_hint = (
            f"<period_target>{target_revenue}</period_target>\n"
            "<target_rule>Report variance to target in currency and percent.</target_rule>"
            if target_revenue
            else "<period_target>None supplied</period_target>\n"
                 "<target_rule>Compute pipeline coverage against required new business.</target_rule>"
        )
        prompt = _build_revenue_prompt(
            context_block=context_block, profile=profile, target_hint=target_hint,
            window_selling_days=window_selling_days, baseline=baseline,
        )
        required_keys = REVENUE_REQUIRED_KEYS

    elif target_key == "Inventory Demand":
        profile = INVENTORY_RISK_PROFILES.get(risk_key, INVENTORY_RISK_PROFILES[DEFAULT_RISK_KEY])
        prompt = _build_inventory_prompt(
            context_block=context_block, profile=profile, baseline=baseline,
            window_selling_days=window_selling_days,
        )
        required_keys = INVENTORY_REQUIRED_KEYS

    elif target_key == "Resource Capacity":
        profile = CAPACITY_RISK_PROFILES.get(risk_key, CAPACITY_RISK_PROFILES[DEFAULT_RISK_KEY])
        prompt = _build_capacity_prompt(context_block=context_block, profile=profile, baseline=baseline)
        required_keys = CAPACITY_REQUIRED_KEYS

    else:  # "Custom" - free text that didn't match anything known
        profile = RISK_PROFILES.get(risk_key, RISK_PROFILES[DEFAULT_RISK_KEY])
        prompt = _build_custom_prompt(context_block=context_block, profile=profile, raw_request=target_raw)
        required_keys = REVENUE_REQUIRED_KEYS

    try:
        structured = await run_node_fn(
            prompt=prompt, user_label=user_label, msg_type="forecast",
            session_id=session_id, session_tenant_id=session_tenant_id,
            resolved_tenant_ids=resolved_tenant_ids or [], resolved_company_ids=resolved_company_ids or [],
        )
        guarded = _guard_payload(
            structured, required_keys=required_keys, profile=profile,
            period_label=period_label, baseline=baseline, resolution_note=resolution_note,
        )
        return {
            **guarded,
            "session_id": session_id,
            # Old and new key names for target, so a frontend built against
            # either contract keeps working during the transition - plus the
            # same raw/resolved transparency now extended to risk_profile and
            # horizon, so nothing is silently rewritten without the caller
            # being able to see what happened.
            "scope": target_raw,
            "resolved_scope": target_key,
            "forecast_target": target_raw,
            "resolved_target": target_key,
            "risk_profile": risk_raw or risk_key,
            "resolved_risk_profile": risk_key,
            "horizon": horizon_raw or horizon,
            "resolved_horizon": horizon,
            "window": {
                "start": window_start.isoformat(),
                "end": window_end.isoformat(),
                "calendar_days": window_days,
                "selling_days": window_selling_days,
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        log_error("run_forecast", e)
        raise HTTPException(status_code=500, detail="Failed to generate forecast. Please try again.")

# Backward compatibility alias
execute_forecast = execute_cfo_forecast
