# api/agent/deterministic_reasoning.py

import re
import calendar
from .db import run_query
from .tools_refactored.common import normalize_business_text_for_intent, calculate_ratio

def _month_bounds(year, month):
    last_day = calendar.monthrange(year, month)[1]
    return f"{year:04d}-{month:02d}-01", f"{year:04d}-{month:02d}-{last_day:02d}"

def _get_sales_metrics(tenant_id, company_ids, start, end):
    params = {"tenant_id": tenant_id, "start": start, "end": end}
    placeholders = [f":c{i}" for i in range(len(company_ids))]
    for i, cid in enumerate(company_ids): params[f"c{i}"] = cid
    
    rows = run_query(f"""
        SELECT COALESCE(SUM(amount_total), 0) AS revenue, COUNT(*) AS count
        FROM fact_sales_orders
        WHERE tenant_id = :tenant_id AND company_id IN ({", ".join(placeholders)})
          AND state IN ('sale', 'done') AND date_order >= :start AND date_order <= :end
    """, params)
    return {"revenue": float(rows[0]["revenue"]), "count": int(rows[0]["count"])}

def analyze_sales_change(tenant_id: str, message: str, company_ids: list[int]) -> str | None:
    text = normalize_business_text_for_intent(message)
    # Simplified regex for demo
    pattern = r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\s+(\d{4})\b"
    matches = re.findall(pattern, text)
    if len(matches) < 2: return None
    
    # Logic for comparing two periods ...
    return f"Sales change analysis between {matches[0]} and {matches[1]} for tenant {tenant_id}."

def analyze_revenue_gap(tenant_id: str, message: str, company_ids: list[int]) -> str | None:
    text = normalize_business_text_for_intent(message)
    if "accounting" in text and "sales" in text and any(x in text for x in ["why", "diff", "gap"]):
        return "Deterministic revenue gap analysis result."
    return None
