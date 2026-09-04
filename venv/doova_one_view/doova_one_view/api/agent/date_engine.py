# doova_one_view/api/agent/date_engine.py
"""
Enterprise Date & Comparison Engine for AI Agent & Reporting.

Provides unified, deterministic date resolution across all chat tools and report generators:
1. Natural language & macro-period parsing ("Q3 2026", "last quarter", "past 6 months", "last 30 days")
2. ISO date validation and normalization
3. Mathematical comparison basis derivation (MoM, QoQ, YoY, HoH, WoW)
4. Prior period calculation with leap year and calendar quarter boundary safety
"""

import re
from datetime import date, datetime, timedelta
from typing import Any, Optional, Tuple


def normalize_iso_date(val: Any) -> Optional[str]:
    """
    Safely normalizes various date inputs into strict ISO 'YYYY-MM-DD'.
    Accepts: ISO string, ISO with timestamp, date/datetime objects.
    Returns None if input is invalid, empty, or unparseable.
    """
    if not val:
        return None
    if isinstance(val, (datetime, date)):
        return val.strftime("%Y-%m-%d")

    val_str = str(val).strip()
    if not val_str:
        return None

    # Handle ISO date or ISO datetime
    match = re.match(r"^(\d{4}-\d{2}-\d{2})", val_str)
    if match:
        iso_part = match.group(1)
        try:
            datetime.strptime(iso_part, "%Y-%m-%d")
            return iso_part
        except ValueError:
            return None

    return None


def resolve_as_of_date(
    val: Any,
    reference_date: Optional[date] = None,
    fallback_date: Optional[str] = None,
) -> str:
    """
    Deterministically resolves a point-in-time snapshot date ('as_of_date')
    from an ISO date, date/datetime object, or macro period string (e.g. 'Q3 2026', 'last month').
    
    If given a period, it extracts the period's END DATE (the closing balance date).
    Example:
        'Q3 2026' -> '2026-09-30'
        'last month' (in Sept 2026) -> '2026-08-31'
        '2026-06-15' -> '2026-06-15'
    """
    ref = reference_date or date.today()
    if not val:
        return fallback_date or ref.strftime("%Y-%m-%d")

    # If it's already an ISO date or datetime object
    norm = normalize_iso_date(val)
    if norm:
        return norm

    # If it's a period/macro string e.g. "Q3 2026", "last month", "FY 2025"
    _, e_iso, _ = resolve_period_dates(text=str(val), reference_date=ref, default_to_ytd=False)
    if e_iso:
        return e_iso

    return fallback_date or ref.strftime("%Y-%m-%d")


def _infer_comparison_label(days: int) -> str:
    """
    Auto-derive the comparison basis label from the span of the date range in days.
    """
    if days <= 1:
        return "Prior Day"
    elif 6 <= days <= 8:
        return "Prior Week (WoW)"
    elif 13 <= days <= 15:
        return "Prior 2 Weeks"
    elif 27 <= days <= 31:
        return "Prior Month (MoM)"
    elif 88 <= days <= 95:
        return "Prior Quarter (QoQ)"
    elif 178 <= days <= 186:
        return "Prior 6 Months (HoH)"
    elif 363 <= days <= 367:
        return "Same Period Prior Year (YoY)"
    else:
        return "Same Period Prior Year (YoY)"


def resolve_comparison_dates(
    start_date: str | None,
    end_date: str | None,
    comparison_label: Optional[str] = None,
    comparison_type: Optional[str] = None,
    reference_date: Optional[date] = None,
) -> Tuple[str, str, str]:
    """
    Auto-derives prior comparison period (prior_start, prior_end) ISO date strings
    and the resolved comparison label (MoM, QoQ, YoY, HoH, WoW, etc.).
    
    Returns:
        (prior_start_iso, prior_end_iso, resolved_comparison_label)
    """
    ref = reference_date or date.today()
    current_year = ref.year

    if not start_date or not end_date:
        p_start = f"{current_year - 1}-01-01"
        p_end = f"{current_year - 1}-{ref.strftime('%m-%d')}"
        return p_start, p_end, "Same Period Prior Year (YoY)"

    try:
        s_dt = datetime.strptime(start_date, "%Y-%m-%d").date()
        e_dt = datetime.strptime(end_date, "%Y-%m-%d").date()
    except Exception:
        p_start = f"{current_year - 1}-01-01"
        p_end = f"{current_year - 1}-{ref.strftime('%m-%d')}"
        return p_start, p_end, "Same Period Prior Year (YoY)"

    span_days = (e_dt - s_dt).days + 1
    c_label = (comparison_label or "").strip()
    c_type = (comparison_type or "").strip()

    # Determine resolved comparison label if not supplied
    if not c_label:
        if c_type == "prior_month":
            c_label = "Prior Month (MoM)"
        elif c_type == "prior_quarter":
            c_label = "Prior Quarter (QoQ)"
        elif c_type == "prior_year" or c_type == "yoy":
            c_label = "Same Period Prior Year (YoY)"
        else:
            c_label = _infer_comparison_label(span_days)

    # 1. Half-year (HoH / 6 Months)
    if "HoH" in c_label or "6 Months" in c_label or c_type == "prior_half":
        try:
            if s_dt.month == 1 and s_dt.day == 1 and e_dt.month == 6 and e_dt.day == 30:
                p_start = date(s_dt.year - 1, 7, 1)
                p_end = date(s_dt.year - 1, 12, 31)
                return p_start.strftime("%Y-%m-%d"), p_end.strftime("%Y-%m-%d"), c_label
            elif s_dt.month == 7 and s_dt.day == 1 and e_dt.month == 12 and e_dt.day == 31:
                p_start = date(s_dt.year, 1, 1)
                p_end = date(s_dt.year, 6, 30)
                return p_start.strftime("%Y-%m-%d"), p_end.strftime("%Y-%m-%d"), c_label
        except Exception:
            pass
        prior_end_dt = s_dt - timedelta(days=1)
        prior_start_dt = prior_end_dt - timedelta(days=span_days - 1)
        return prior_start_dt.strftime("%Y-%m-%d"), prior_end_dt.strftime("%Y-%m-%d"), c_label

    # 2. Month-over-Month (MoM)
    elif c_type == "prior_month" or "MoM" in c_label or (("Month" in c_label or "month" in c_label) and "6 Months" not in c_label):
        try:
            first_of_period = s_dt.replace(day=1)
            prior_end_dt = first_of_period - timedelta(days=1)
            prior_start_dt = prior_end_dt.replace(day=1)
            return prior_start_dt.strftime("%Y-%m-%d"), prior_end_dt.strftime("%Y-%m-%d"), c_label
        except Exception:
            prior_end_dt = s_dt - timedelta(days=1)
            prior_start_dt = prior_end_dt - timedelta(days=span_days - 1)
            return prior_start_dt.strftime("%Y-%m-%d"), prior_end_dt.strftime("%Y-%m-%d"), c_label

    # 3. Quarter-over-Quarter (QoQ)
    elif c_type == "prior_quarter" or "QoQ" in c_label or "Quarter" in c_label:
        try:
            # Standard calendar quarter alignment (starts 1st of Jan/Apr/Jul/Oct)
            if s_dt.day == 1 and s_dt.month in (1, 4, 7, 10):
                if s_dt.month == 1:
                    prior_start_dt = date(s_dt.year - 1, 10, 1)
                    prior_end_dt = date(s_dt.year - 1, 12, 31)
                elif s_dt.month == 4:
                    prior_start_dt = date(s_dt.year, 1, 1)
                    prior_end_dt = date(s_dt.year, 3, 31)
                elif s_dt.month == 7:
                    prior_start_dt = date(s_dt.year, 4, 1)
                    prior_end_dt = date(s_dt.year, 6, 30)
                else:  # 10
                    prior_start_dt = date(s_dt.year, 7, 1)
                    prior_end_dt = date(s_dt.year, 9, 30)
                return prior_start_dt.strftime("%Y-%m-%d"), prior_end_dt.strftime("%Y-%m-%d"), c_label

            # Custom span quarter
            prior_end_dt = s_dt - timedelta(days=1)
            prior_start_dt = prior_end_dt - timedelta(days=span_days - 1)
            return prior_start_dt.strftime("%Y-%m-%d"), prior_end_dt.strftime("%Y-%m-%d"), c_label
        except Exception:
            prior_end_dt = s_dt - timedelta(days=1)
            prior_start_dt = prior_end_dt - timedelta(days=span_days - 1)
            return prior_start_dt.strftime("%Y-%m-%d"), prior_end_dt.strftime("%Y-%m-%d"), c_label

    # 4. Sequential periods (WoW, Day, Sequential)
    elif any(k in c_label for k in ("WoW", "Week", "Day", "Sequential")):
        prior_end_dt = s_dt - timedelta(days=1)
        prior_start_dt = prior_end_dt - timedelta(days=span_days - 1)
        return prior_start_dt.strftime("%Y-%m-%d"), prior_end_dt.strftime("%Y-%m-%d"), c_label

    # 5. Default: Same Period Prior Year (YoY)
    else:
        try:
            try:
                prior_start_dt = s_dt.replace(year=s_dt.year - 1)
            except ValueError:
                # Leap day Feb 29 -> Feb 28
                prior_start_dt = s_dt.replace(year=s_dt.year - 1, day=28)
            try:
                prior_end_dt = e_dt.replace(year=e_dt.year - 1)
            except ValueError:
                prior_end_dt = e_dt.replace(year=e_dt.year - 1, day=28)
            return prior_start_dt.strftime("%Y-%m-%d"), prior_end_dt.strftime("%Y-%m-%d"), c_label
        except Exception:
            p_start = f"{current_year - 1}-01-01"
            p_end = f"{current_year - 1}-{ref.strftime('%m-%d')}"
            return p_start, p_end, c_label


def format_period_label(start_date: str, end_date: str) -> str:
    """Formats two ISO dates into a human-readable string e.g. 'Jul 01, 2026 – Sep 30, 2026'."""
    try:
        s_dt = datetime.strptime(start_date, "%Y-%m-%d")
        e_dt = datetime.strptime(end_date, "%Y-%m-%d")
        return f"{s_dt.strftime('%b %d, %Y')} – {e_dt.strftime('%b %d, %Y')}"
    except Exception:
        return f"{start_date} – {end_date}"


def resolve_period_dates(
    text: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    reference_date: Optional[date] = None,
    default_to_ytd: bool = True,
) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Unified date & period resolver.
    
    Given optional natural language query text or explicit start_date/end_date arguments,
    deterministically returns:
        (iso_start, iso_end, formatted_label)
        
    Handles:
        - Exact ISO dates: '2026-07-01' to '2026-09-30'
        - Quarters: 'Q1'..'Q4', 'Q3 2026', 'last quarter', 'this quarter'
        - Months: 'this month', 'last month', 'past N months'
        - Days/Weeks: 'today', 'yesterday', 'past N days', 'N days before YYYY-MM-DD'
        - Years/Halves: 'YTD', 'this year', 'last year', 'FY 2025', 'H1', 'H2'
        - Explicit ranges: 'from YYYY-MM-DD to YYYY-MM-DD', 'between ... and ...'
    """
    ref = reference_date or date.today()
    current_year = ref.year

    norm_start = normalize_iso_date(start_date)
    norm_end = normalize_iso_date(end_date)

    search_text = (text or "").lower().strip()
    # Also check if start_date itself was passed as a macro like "Q3" or "last month"
    if start_date and not norm_start:
        search_text = f"{start_date} {search_text}".strip().lower()

    # If both start and end dates are already valid ISO format:
    if norm_start and norm_end:
        label = format_period_label(norm_start, norm_end)
        # Check if matches standard quarter or full year and append badge
        try:
            s_dt = datetime.strptime(norm_start, "%Y-%m-%d").date()
            e_dt = datetime.strptime(norm_end, "%Y-%m-%d").date()
            if s_dt.month == 1 and s_dt.day == 1 and e_dt.month == 12 and e_dt.day == 31 and s_dt.year == e_dt.year:
                label = f"Jan 01, {s_dt.year} – Dec 31, {s_dt.year} (FY {s_dt.year})"
            elif s_dt.day == 1 and s_dt.year == e_dt.year:
                if s_dt.month == 1 and e_dt.month == 3 and e_dt.day == 31:
                    label += f" (Q1 {s_dt.year})"
                elif s_dt.month == 4 and e_dt.month == 6 and e_dt.day == 30:
                    label += f" (Q2 {s_dt.year})"
                elif s_dt.month == 7 and e_dt.month == 9 and e_dt.day == 30:
                    label += f" (Q3 {s_dt.year})"
                elif s_dt.month == 10 and e_dt.month == 12 and e_dt.day == 31:
                    label += f" (Q4 {s_dt.year})"
        except Exception:
            pass
        return norm_start, norm_end, label

    # If search_text is empty and explicit ISO dates are not provided:
    if not search_text:
        if default_to_ytd:
            ytd_start = f"{current_year}-01-01"
            ytd_end = ref.strftime("%Y-%m-%d")
            label = f"Jan 01, {current_year} – {ref.strftime('%b %d, %Y')} (YTD)"
            return ytd_start, ytd_end, label
        return None, None, None

    # 1. Check for explicit date ranges: 'from YYYY-MM-DD to YYYY-MM-DD' or 'between YYYY-MM-DD and YYYY-MM-DD'
    m_range = re.search(r"\b(?:from|between)\s+(\d{4}-\d{2}-\d{2})\s+(?:to|and)\s+(\d{4}-\d{2}-\d{2})\b", search_text)
    if m_range:
        s_iso = m_range.group(1)
        e_iso = m_range.group(2)
        return s_iso, e_iso, format_period_label(s_iso, e_iso)

    # 2. Check for N days before a specific date: '20 days before 2026-08-31'
    m_days_date = re.search(r"\b(\d+)\s+days?\s+before\s+(\d{4}-\d{2}-\d{2})\b", search_text)
    if m_days_date:
        n_days = int(m_days_date.group(1))
        e_dt = datetime.strptime(m_days_date.group(2), "%Y-%m-%d").date()
        s_dt = e_dt - timedelta(days=n_days)
        s_iso = s_dt.strftime("%Y-%m-%d")
        e_iso = e_dt.strftime("%Y-%m-%d")
        return s_iso, e_iso, f"{format_period_label(s_iso, e_iso)} ({n_days} Days)"

    # 3. Check for past/last N days
    m_days = re.search(r"\b(?:past|last|previous)\s+(\d+)\s+days?\b|\b(\d+)\s+days?\s+(?:before today|prior|ago)\b", search_text)
    if m_days:
        n_days = int(m_days.group(1) or m_days.group(2) or 30)
        s_dt = ref - timedelta(days=n_days)
        s_iso = s_dt.strftime("%Y-%m-%d")
        e_iso = ref.strftime("%Y-%m-%d")
        return s_iso, e_iso, f"{format_period_label(s_iso, e_iso)} ({n_days} Days)"

    # 4. Check for past/last N months
    m_months = re.search(r"\b(?:past|last|previous)\s+(\d+)\s+months?\b|\b(\d+)\s+months?\s+(?:before|prior|ago)\b", search_text)
    if m_months:
        n_months = int(m_months.group(1) or m_months.group(2) or 3)
        start_month = ref.month - n_months + 1
        start_year = ref.year
        while start_month <= 0:
            start_month += 12
            start_year -= 1
        s_dt = date(start_year, start_month, 1)
        s_iso = s_dt.strftime("%Y-%m-%d")
        e_iso = ref.strftime("%Y-%m-%d")
        return s_iso, e_iso, f"{s_dt.strftime('%b 01, %Y')} – {ref.strftime('%b %d, %Y')} ({n_months} Months)"

    # 5. Specific calendar quarter with optional year: 'Q1 2025', '2026 Q3', 'Q3', 'third quarter'
    m_quarter_year = re.search(r"\b(?:q([1-4])\s*(\d{4})|(\d{4})\s*q([1-4]))\b", search_text)
    if m_quarter_year:
        q_num = int(m_quarter_year.group(1) or m_quarter_year.group(4))
        q_yr = int(m_quarter_year.group(2) or m_quarter_year.group(3))
        q_starts = {1: (1, 1), 2: (4, 1), 3: (7, 1), 4: (10, 1)}
        q_ends = {1: (3, 31), 2: (6, 30), 3: (9, 30), 4: (12, 31)}
        sm, sd = q_starts[q_num]
        em, ed = q_ends[q_num]
        s_iso = f"{q_yr}-{sm:02d}-{sd:02d}"
        e_iso = f"{q_yr}-{em:02d}-{ed:02d}"
        s_dt = date(q_yr, sm, sd)
        e_dt = date(q_yr, em, ed)
        label = f"{s_dt.strftime('%b 01, %Y')} – {e_dt.strftime('%b %d, %Y')} (Q{q_num} {q_yr})"
        return s_iso, e_iso, label

    # 6. Specific quarter current year: 'Q1', 'Q2', 'Q3', 'Q4', 'first quarter', 'second quarter', 'third quarter', 'fourth quarter'
    if re.search(r"\bq1\b|\bfirst quarter\b", search_text):
        s_iso = f"{current_year}-01-01"
        e_iso = f"{current_year}-03-31"
        return s_iso, e_iso, f"Jan 01, {current_year} – Mar 31, {current_year} (Q1)"
    if re.search(r"\bq2\b|\bsecond quarter\b", search_text):
        s_iso = f"{current_year}-04-01"
        e_iso = f"{current_year}-06-30"
        return s_iso, e_iso, f"Apr 01, {current_year} – Jun 30, {current_year} (Q2)"
    if re.search(r"\bq3\b|\bthird quarter\b", search_text):
        s_iso = f"{current_year}-07-01"
        e_iso = f"{current_year}-09-30"
        return s_iso, e_iso, f"Jul 01, {current_year} – Sep 30, {current_year} (Q3)"
    if re.search(r"\bq4\b|\bfourth quarter\b", search_text):
        s_iso = f"{current_year}-10-01"
        e_iso = f"{current_year}-12-31"
        return s_iso, e_iso, f"Oct 01, {current_year} – Dec 31, {current_year} (Q4)"

    # 7. 'last quarter' / 'prior quarter' / 'previous quarter' / 'past quarter' / 'qoq'
    if re.search(r"\blast\s+quarter\b|\bpast\s+quarter\b|\bprevious\s+quarter\b|\bprior\s+quarter\b|\bqoq\b", search_text):
        curr_q = (ref.month - 1) // 3 + 1
        prev_q = 4 if curr_q == 1 else curr_q - 1
        q_year = current_year - 1 if curr_q == 1 else current_year
        q_starts = {1: f"{q_year}-01-01", 2: f"{q_year}-04-01", 3: f"{q_year}-07-01", 4: f"{q_year}-10-01"}
        q_ends = {1: f"{q_year}-03-31", 2: f"{q_year}-06-30", 3: f"{q_year}-09-30", 4: f"{q_year}-12-31"}
        q_labels = {
            1: f"Jan 01, {q_year} – Mar 31, {q_year} (Q1)",
            2: f"Apr 01, {q_year} – Jun 30, {q_year} (Q2)",
            3: f"Jul 01, {q_year} – Sep 30, {q_year} (Q3)",
            4: f"Oct 01, {q_year} – Dec 31, {q_year} (Q4)",
        }
        return q_starts[prev_q], q_ends[prev_q], q_labels[prev_q]

    # 8. 'this quarter' / 'current quarter'
    if re.search(r"\bthis\s+quarter\b|\bcurrent\s+quarter\b", search_text):
        curr_q = (ref.month - 1) // 3 + 1
        q_starts = {1: f"{current_year}-01-01", 2: f"{current_year}-04-01", 3: f"{current_year}-07-01", 4: f"{current_year}-10-01"}
        s_iso = q_starts[curr_q]
        e_iso = ref.strftime("%Y-%m-%d")
        s_dt = datetime.strptime(s_iso, "%Y-%m-%d").date()
        return s_iso, e_iso, f"{s_dt.strftime('%b 01, %Y')} – {ref.strftime('%b %d, %Y')} (Q{curr_q} to Date)"

    # 9. 'this month' / 'current month'
    if re.search(r"\bthis\s+month\b|\bcurrent\s+month\b", search_text):
        s_dt = ref.replace(day=1)
        s_iso = s_dt.strftime("%Y-%m-%d")
        e_iso = ref.strftime("%Y-%m-%d")
        return s_iso, e_iso, f"{s_dt.strftime('%b 01, %Y')} – {ref.strftime('%b %d, %Y')} (MTD)"

    # 10. 'last month' / 'past month' / 'previous month' / 'prior month' / 'mom'
    if any(w in search_text for w in ("past month", "this past month", "previous month", "prior month", "month before", "last month", "mom")):
        first_of_this_month = ref.replace(day=1)
        last_month_end = first_of_this_month - timedelta(days=1)
        last_month_start = last_month_end.replace(day=1)
        s_iso = last_month_start.strftime("%Y-%m-%d")
        e_iso = last_month_end.strftime("%Y-%m-%d")
        return s_iso, e_iso, f"{last_month_start.strftime('%b 01, %Y')} – {last_month_end.strftime('%b %d, %Y')}"

    # 11. 'past 6 months' / 'last 6 months' / 'h1' / 'first half'
    if re.search(r"\bpast\s+6\s+months\b|\blast\s+6\s+months\b|\bh1\b|\bfirst half\b", search_text):
        s_iso = f"{current_year}-01-01"
        e_iso = f"{current_year}-06-30"
        return s_iso, e_iso, f"Jan 01, {current_year} – Jun 30, {current_year} (H1 {current_year})"

    # 12. 'h2' / 'second half'
    if re.search(r"\bh2\b|\bsecond half\b", search_text):
        s_iso = f"{current_year}-07-01"
        e_iso = f"{current_year}-12-31"
        return s_iso, e_iso, f"Jul 01, {current_year} – Dec 31, {current_year} (H2 {current_year})"

    # 13. 'last year' / 'past year' / 'prior year' / 'fy YYYY'
    match_yr = re.search(r"\bfy\s*(\d{4})\b|\b(?:last|past|prior)\s+year\b", search_text)
    if match_yr:
        target_yr = int(match_yr.group(1)) if match_yr.group(1) else current_year - 1
        s_iso = f"{target_yr}-01-01"
        e_iso = f"{target_yr}-12-31"
        return s_iso, e_iso, f"Jan 01, {target_yr} – Dec 31, {target_yr} (FY {target_yr})"

    # 14. 'today'
    if re.search(r"\btoday\b", search_text):
        iso_t = ref.strftime("%Y-%m-%d")
        return iso_t, iso_t, f"{ref.strftime('%b %d, %Y')} (Today)"

    # 15. 'yesterday'
    if re.search(r"\byesterday\b", search_text):
        yest = ref - timedelta(days=1)
        iso_y = yest.strftime("%Y-%m-%d")
        return iso_y, iso_y, f"{yest.strftime('%b %d, %Y')} (Yesterday)"

    # 16. Fallback default
    if default_to_ytd:
        ytd_start = f"{current_year}-01-01"
        ytd_end = ref.strftime("%Y-%m-%d")
        return ytd_start, ytd_end, f"Jan 01, {current_year} – {ref.strftime('%b %d, %Y')} (YTD)"

    return None, None, None
