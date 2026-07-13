# api/agent/tools_refactored/common.py

import re
from pathlib import Path
from datetime import datetime
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from ..db import run_query
from ..query_context import extract_date_range, normalize_company_ids, build_company_filter_sql
from ..config import AgentConfig

def get_companies_tool(tenant_id: str) -> dict:
    rows = run_query("SELECT id, name FROM dim_companies WHERE tenant_id = :tenant_id", {"tenant_id": tenant_id})
    return {"tool_name": "get_companies_tool", "companies": rows}

def get_tenant_profile_tool(tenant_id: str, company_id: int | None = None) -> dict:
    """Fetches the company's industry, sector, and operational context from the database."""
    # dim_companies PK is "id", not "company_id"
    company_f_sql, company_f_params = build_company_filter_sql(tenant_id, company_id, column_name="id")
    company_params = {"tenant_id": tenant_id, **company_f_params}

    # Try to get basic company info
    rows = run_query(
        f"""SELECT
                name,
                'Not Specified' AS industry,
                'Not Specified' AS company_type,
                COALESCE(currency_name, currency_code, 'USD') AS currency
            FROM dim_companies
            WHERE tenant_id = :tenant_id {company_f_sql}
            LIMIT 5""",
        company_params,
    )

    # Infer business type from product and transaction data (tenant-scoped only, no company filter)
    product_stats = run_query(
        """SELECT
                COUNT(DISTINCT CASE WHEN product_type = 'product' THEN id END) AS physical_products,
                COUNT(DISTINCT CASE WHEN product_type = 'service' THEN id END) AS services,
                COUNT(DISTINCT CASE WHEN product_type = 'consu' THEN id END) AS consumables
            FROM dim_products
            WHERE tenant_id = :tenant_id""",
        {"tenant_id": tenant_id},
    )

    ps = product_stats[0] if product_stats else {}
    physical = int(ps.get("physical_products") or 0)
    services = int(ps.get("services") or 0)

    if services > physical * 2:
        inferred_type = "Service-Based"
    elif physical > services * 2:
        inferred_type = "Product/Retail-Based"
    else:
        inferred_type = "Hybrid (Product + Service)"

    return {
        "tool_name": "get_tenant_profile_tool",
        "companies": [
            {"name": r["name"], "industry": r["industry"], "type": r["company_type"], "currency": r["currency"]}
            for r in rows
        ],
        "inferred_business_model": inferred_type,
        "product_count": physical,
        "service_count": services,
    }

def normalize_business_text_for_intent(message: str | None) -> str:
    """
    Lightweight intent normalizer to fix typos and map phrases.
    """
    text = (message or "").lower().strip()

    replacements = {
        "revnue": "revenue", "revenu": "revenue", "revanue": "revenue",
        "sale summery": "sales summary", "sales summery": "sales summary",
        "salse": "sales", "seles": "sales", "seling": "selling",
        "inventry": "inventory", "inventroy": "inventory", "invntory": "inventory",
        "stok": "stock", "stcok": "stock", "custmer": "customer",
        "custmers": "customers", "costumer": "customer", "costumers": "customers",
        "prodcut": "product", "prodcuts": "products", "prduct": "product",
        "prducts": "products", "grph": "graph", "grahp": "graph",
        "char": "chart", "chrt": "chart", "reprt": "report",
        "repport": "report", "pdfs": "pdf",
    }

    for wrong, correct in replacements.items():
        text = text.replace(wrong, correct)

    return " ".join(text.split())

def is_graph_request(text: str) -> bool:
    text = normalize_business_text_for_intent(text)
    has_keywords = any(kw in text for kw in ["plot", "graph", "chart", "visualize"])
    has_structured_data = bool(re.search(r"\d+\s*[:\-]\s*\d+", text))
    return has_keywords or has_structured_data

def extract_graph_data(text: str) -> dict:
    pairs = re.findall(r"(\d+)\s*[:\-]\s*\d+", text)
    if pairs:
        x = [int(a) for a, _ in pairs]
        y = [int(b) for _, b in pairs]
        return {"x": x, "y": y, "points": [{"x": xv, "y": yv} for xv, yv in zip(x, y)]}
    
    numbers = list(map(int, re.findall(r"\d+", text)))
    if len(numbers) >= 2:
        x = list(range(1, len(numbers) + 1))
        return {"x": x, "y": numbers, "points": [{"x": xv, "y": yv} for xv, yv in zip(x, numbers)]}
    
    return {"x": [], "y": [], "points": []}

def generate_pdf(text: str, filename: str = "output.pdf") -> str:
    c = canvas.Canvas(filename, pagesize=letter)
    width, height = letter
    y = height - 40
    for line in text.split("\n"):
        c.drawString(40, y, line[:100])
        y -= 15
        if y < 40:
            c.showPage()
            y = height - 40
    c.save()
    return filename

def calculate_ratio(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator != 0 else 0.0

def build_currency_case_sql(column: str, tenant_id: str, base_currency: str | None, currency_column: str = "currency_code") -> str:
    """Builds a dynamic SQL CASE WHEN block to apply currency conversion to a column."""
    if not base_currency:
        return column

    try:
        from doova_one_view.api.kpi.service import _get_rate_map
        rate_map = _get_rate_map()
        
        # Inject the tenant's base currency with a rate of 1.0 so conversions to/from it work
        from doova_one_view.api.agent.utils import get_tenant_currency
        tenant_base = get_tenant_currency(tenant_id)
        if tenant_base and tenant_base not in rate_map:
            rate_map[tenant_base] = 1.0

        if not rate_map or base_currency not in rate_map:
            return column
            
        target_rate = rate_map[base_currency]
        if target_rate == 0:
            return column

        cases = []
        for cur_code, row_rate in rate_map.items():
            if not cur_code or row_rate == 0:
                continue
                
            # Factor to convert from cur_code to base_currency
            # value_in_base = value_in_cur_code / row_rate
            # value_in_target = value_in_base * target_rate
            # therefore factor = target_rate / row_rate
            factor = target_rate / row_rate
            
            # Avoid emitting " * 1.0 " if the factor is exactly 1
            if abs(factor - 1.0) < 0.0001:
                continue
                
            cases.append(f"WHEN {currency_column} = '{cur_code}' THEN {column} * {factor}")
            
        if not cases:
            return column
            
        case_str = " ".join(cases)
        return f"(CASE {case_str} ELSE {column} END)"
    except Exception as e:
        import logging
        logging.error(f"Error building currency case sql: {e}")
        return column
