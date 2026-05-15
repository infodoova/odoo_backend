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
    rows = run_query("SELECT odoo_id as id, name FROM dim_companies WHERE tenant_id = :tenant_id", {"tenant_id": tenant_id})
    return {"tool_name": "get_companies_tool", "companies": rows}

def get_tenant_profile_tool(tenant_id: str, company_id: int | None = None) -> dict:
    """Fetches the company's industry, sector, and operational context from the database."""
    params = {"tenant_id": tenant_id}
    f_sql, f_params = build_company_filter_sql(tenant_id, company_id)
    params.update(f_params)

    # Try to get industry from company settings
    rows = run_query(
        f"""SELECT 
                name,
                COALESCE(industry, 'Unknown') AS industry,
                COALESCE(company_type, 'Unknown') AS company_type,
                COALESCE(currency_name, 'USD') AS currency
            FROM dim_companies
            WHERE tenant_id = :tenant_id {f_sql}
            LIMIT 5""",
        params,
    )

    # Infer business type from product and transaction data
    product_stats = run_query(
        f"""SELECT 
                COUNT(DISTINCT CASE WHEN type = 'product' THEN id END) AS physical_products,
                COUNT(DISTINCT CASE WHEN type = 'service' THEN id END) AS services,
                COUNT(DISTINCT CASE WHEN type = 'consu' THEN id END) AS consumables
            FROM dim_products
            WHERE tenant_id = :tenant_id {f_sql}""",
        params,
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
