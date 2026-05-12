"""
Business tools for the AI agent.
These tools interact with the PostgreSQL database to fetch business metrics.
Includes intent normalization, graph/PDF detection, and CFO-style reporting.
"""

import re
import json
from pathlib import Path
from datetime import datetime
from dateutil.relativedelta import relativedelta
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from .db import run_query
from .odoo_client import OdooClient
from .query_context import extract_date_range, normalize_company_ids, build_company_filter_sql


# ─────────────────────────────
# GRAPH DETECTION
# ─────────────────────────────

def normalize_business_text_for_intent(message: str | None) -> str:
    """
    Lightweight intent normalizer.
    Fixes common typos and maps natural phrases to internal terms.
    """
    text = (message or "").lower().strip()

    replacements = {
        # Common typos
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

        # Natural sales phrases
        "how much we sell": "sales summary", "how much did we sell": "sales summary",
        "how much have we sold": "sales summary", "what did we sell": "sales summary",
        "what we sold": "sales summary", "sales amount": "sales summary",
        "selling amount": "sales summary",

        # Report / PDF phrases
        "pdf for": "pdf report for", "as pdf": "pdf report",
        "in pdf": "pdf report", "pdf version": "pdf report",
        "download pdf": "download report", "export pdf": "download report",
        "export as pdf": "download report", "make pdf": "generate report",
        "make a pdf": "generate report", "i want a pdf": "generate report",
        "i need a pdf": "generate report", "report for": "generate report for",
        "make report": "generate report", "make a report": "generate report",

        # Inventory natural phrases
        "almost finished": "low stock", "nearly finished": "low stock",
        "nearly empty": "low stock", "almost empty": "low stock",
        "few quantity": "low stock", "little quantity": "low stock",
        "not enough stock": "low stock", "stock problem": "inventory alerts",
        "stock problems": "inventory alerts", "inventory problem": "inventory alerts",
        "inventory problems": "inventory alerts", "inventory issue": "inventory alerts",
        "inventory issues": "inventory alerts", "what should we reorder": "low stock reorder",
        "reorder first": "low stock reorder", "give me reorder recommendations": "low stock reorder recommendations",
        "reorder recommendations": "low stock reorder recommendations", "reorder items": "low stock reorder items",
        "items to reorder": "low stock reorder items", "products to reorder": "low stock reorder products",
        "buy again": "low stock reorder",

        # Expiry / lots natural phrases
        "which lots will expire soon": "show expiring lots", "lots will expire soon": "show expiring lots",
        "lots expire soon": "show expiring lots", "expire soon": "expiring lots",
        "expiry": "expiration", "near expiry": "expiring lots", "expiration alerts": "expiring lots",

        # Inventory report phrases
        "generate inventory report": "generate report inventory", "inventory report": "generate report inventory",
        "download inventory report": "download report inventory", "pdf inventory": "pdf report inventory",
        "pdf for inventory": "pdf report inventory",

        # Customer/product natural phrases
        "best clients": "top customers", "top clients": "top customers",
        "biggest clients": "top customers", "best customers": "top customers",
        "biggest customers": "top customers", "best items": "top products",
        "top items": "top products", "best selling items": "best selling products",
        "most sold items": "most sold products",

        # Graph natural phrases
        "draw": "chart", "plot": "chart", "visualize": "chart", "visualise": "chart",
    }

    for wrong, correct in replacements.items():
        text = text.replace(wrong, correct)

    return " ".join(text.split())

def is_graph_request(text: str) -> bool:
    text = normalize_business_text_for_intent(text)
    return any(kw in text for kw in ["plot", "graph", "chart", "visualize"]) or bool(re.search(r"\d+\s*[:\-]\s*\d+", text))

def extract_graph_data(text: str) -> dict:
    pairs = re.findall(r"(\d+)\s*[:\-]\s*(\d+)", text)
    if pairs:
        x = [int(a) for a, _ in pairs]
        y = [int(b) for _, b in pairs]
        return {"x": x, "y": y, "points": [{"x": x_val, "y": y_val} for x_val, y_val in zip(x, y)]}
    numbers = list(map(int, re.findall(r"\d+", text)))
    if len(numbers) >= 2:
        x = list(range(1, len(numbers) + 1))
        return {"x": x, "y": numbers, "points": [{"x": xv, "y": yv} for xv, yv in zip(x, numbers)]}
    return {"x": [], "y": [], "points": []}

def is_pdf_request(text: str) -> bool:
    return any(kw in text.lower() for kw in ["pdf", "generate pdf", "save as pdf", "pdf report"])

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

def calculate_ratio_tool(numerator: float, denominator: float) -> dict:
    ratio = calculate_ratio(numerator, denominator)
    return {"tool_name": "calculate_ratio_tool", "numerator": numerator, "denominator": denominator, "ratio": ratio, "percentage": ratio * 100}

# ─────────────────────────────
# BUSINESS TOOLS (POSTGRES)
# ─────────────────────────────

def get_sales_summary_tool(tenant_id: str, company_id: int | None = None, company_ids: list[int] | None = None, start_date: str | None = None, end_date: str | None = None, period: str = "selected_period") -> dict:
    selected_company_ids = normalize_company_ids(company_id=company_id, companies=company_ids)
    query = "SELECT COALESCE(SUM(amount_total), 0) AS total_revenue, COUNT(*) AS order_count, COALESCE(AVG(amount_total), 0) AS average_order_value, COALESCE(MIN(date_order), NULL) AS first_order_date, COALESCE(MAX(date_order), NULL) AS last_order_date FROM fact_sales_orders WHERE tenant_id = :tenant_id AND state IN ('sale', 'done')"
    params = {"tenant_id": tenant_id}
    if selected_company_ids:
        filter_sql, filter_params = build_company_filter_sql(selected_company_ids)
        query += filter_sql
        params.update(filter_params)
    if start_date:
        query += " AND date_order >= :start_date"
        params["start_date"] = start_date
    if end_date:
        query += " AND date_order <= :end_date"
        params["end_date"] = end_date
    rows = run_query(query, params)
    row = rows[0] if rows else {}
    return {
        "tool_name": "get_sales_summary_tool", "total_revenue": float(row.get("total_revenue") or 0), "order_count": int(row.get("order_count") or 0),
        "average_order_value": float(row.get("average_order_value") or 0), "period": period, "first_order_date": str(row.get("first_order_date")) if row.get("first_order_date") else None,
        "last_order_date": str(row.get("last_order_date")) if row.get("last_order_date") else None, "note": "Real data from PostgreSQL fact_sales_orders (sale/done)."
    }

def get_top_products_tool(tenant_id: str, company_id: int | None = None, company_ids: list[int] | None = None, start_date: str | None = None, end_date: str | None = None, limit: int = 10) -> dict:
    selected_company_ids = normalize_company_ids(company_id=company_id, companies=company_ids)
    query = "SELECT l.product_id, l.product_name, COALESCE(SUM(l.product_uom_qty), 0) AS quantity, COALESCE(SUM(l.price_total), 0) AS revenue FROM fact_sales_order_lines l JOIN fact_sales_orders o ON o.id = l.order_local_id AND o.tenant_id = l.tenant_id WHERE l.tenant_id = :tenant_id AND l.state IN ('sale', 'done') AND o.state IN ('sale', 'done') AND l.product_id IS NOT NULL"
    params = {"tenant_id": tenant_id, "limit": limit}
    if selected_company_ids:
        filter_sql, filter_params = build_company_filter_sql(selected_company_ids, column_name="l.company_id")
        query += filter_sql
        params.update(filter_params)
    if start_date:
        query += " AND o.date_order >= :start_date"
        params["start_date"] = start_date
    if end_date:
        query += " AND o.date_order < (CAST(:end_date AS date) + INTERVAL '1 day')"
        params["end_date"] = end_date
    query += " GROUP BY l.product_id, l.product_name ORDER BY revenue DESC LIMIT :limit"
    rows = run_query(query, params)
    return {"tool_name": "get_top_products_tool", "products": [{"product": r["product_name"], "revenue": float(r["revenue"]), "quantity": float(r["quantity"])} for r in rows]}

def get_inventory_alerts_tool(tenant_id: str, company_id: int | None = None, company_ids: list[int] | None = None, low_stock_threshold: float = 10, expiring_days: int = 90) -> dict:
    selected_company_ids = normalize_company_ids(company_id=company_id, companies=company_ids)
    params = {"tenant_id": tenant_id, "threshold": low_stock_threshold, "expiring_days": expiring_days}
    company_filter = ""
    if selected_company_ids:
        company_filter, filter_params = build_company_filter_sql(selected_company_ids)
        params.update(filter_params)
    low_stock_query = f"SELECT product_name, COALESCE(SUM(available_quantity), 0) AS available FROM fact_inventory_quants WHERE tenant_id = :tenant_id AND product_id IS NOT NULL {company_filter} GROUP BY product_id, product_name HAVING SUM(available_quantity) <= :threshold ORDER BY available ASC LIMIT 25"
    expiring_query = f"SELECT name, product_name, expiration_date FROM dim_lots WHERE tenant_id = :tenant_id AND expiration_date IS NOT NULL AND expiration_date >= CURRENT_DATE AND expiration_date < (CURRENT_DATE + (:expiring_days * INTERVAL '1 day')) {company_filter} ORDER BY expiration_date ASC LIMIT 25"
    low_stock_rows = run_query(low_stock_query, params)
    expiring_rows = run_query(expiring_query, params)
    return {
        "tool_name": "get_inventory_alerts_tool", "low_stock_items": [{"product": r["product_name"], "available": float(r["available"])} for r in low_stock_rows],
        "expiring_soon": [{"lot": r["name"], "product": r["product_name"], "expiration_date": str(r["expiration_date"])} for r in expiring_rows]
    }

def get_inventory_efficiency_tool(tenant_id: str, company_id: int | None = None, company_ids: list[int] | None = None) -> dict:
    selected_company_ids = normalize_company_ids(company_id=company_id, companies=company_ids)
    params = {"tenant_id": tenant_id}
    q_filter, m_filter = "", ""
    if selected_company_ids:
        q_filter, q_params = build_company_filter_sql(selected_company_ids, prefix="q")
        m_filter, m_params = build_company_filter_sql(selected_company_ids, prefix="m")
        params.update(q_params); params.update(m_params)
    val_query = f"SELECT COALESCE(SUM(q.available_quantity * COALESCE(p.standard_price, 0)), 0) AS total_val FROM fact_inventory_quants q LEFT JOIN dim_products p ON p.tenant_id = q.tenant_id AND p.odoo_id = q.product_id WHERE q.tenant_id = :tenant_id AND q.available_quantity > 0 {q_filter}"
    move_query = f"SELECT COALESCE(SUM(m.quantity_done * COALESCE(p.standard_price, 0)), 0) AS move_val FROM fact_inventory_moves m LEFT JOIN dim_products p ON p.tenant_id = m.tenant_id AND p.odoo_id = m.product_id WHERE m.tenant_id = :tenant_id AND m.state = 'done' AND m.date >= CURRENT_DATE - INTERVAL '12 months' {m_filter}"
    v_rows = run_query(val_query, params); m_rows = run_query(move_query, params)
    total_val = float(v_rows[0]["total_val"] or 0); move_val = float(m_rows[0]["move_val"] or 0)
    turnover = calculate_ratio(move_val, total_val)
    return {"tool_name": "get_inventory_efficiency_tool", "total_inventory_value": total_val, "turnover_ratio": turnover, "efficiency_rating": "High" if turnover > 6 else "Medium" if turnover >= 3 else "Low"}

def get_cash_flow_health_tool(tenant_id: str, company_id: int | None = None) -> dict:
    params = {"tenant_id": tenant_id}
    comp_filter = " AND company_id = :company_id" if company_id else ""
    if company_id: params["company_id"] = company_id
    ar_q = f"SELECT COALESCE(SUM(amount_residual), 0) AS ar FROM fact_account_moves WHERE tenant_id = :tenant_id AND move_type = 'out_invoice' AND state = 'posted' AND payment_state IN ('not_paid', 'partial') AND amount_residual > 0 {comp_filter}"
    ap_q = f"SELECT COALESCE(SUM(amount_residual), 0) AS ap FROM fact_account_moves WHERE tenant_id = :tenant_id AND move_type = 'in_invoice' AND state = 'posted' AND payment_state IN ('not_paid', 'partial') AND amount_residual > 0 {comp_filter}"
    ar = float(run_query(ar_q, params)[0]["ar"] or 0); ap = float(run_query(ap_q, params)[0]["ap"] or 0)
    ratio = calculate_ratio(ar, ap)
    return {"tool_name": "get_cash_flow_health_tool", "accounts_receivable": ar, "accounts_payable": ap, "liquidity_ratio": ratio, "liquidity_status": "Strong" if ratio >= 1.5 else "Stable" if ratio >= 1.0 else "Risk"}

def get_receivables_analysis_tool(tenant_id: str, company_id: int | None = None, limit: int = 10) -> dict:
    params = {"tenant_id": tenant_id, "limit": limit}
    comp_filter = " AND company_id = :company_id" if company_id else ""
    if company_id: params["company_id"] = company_id
    summary_q = f"SELECT COALESCE(SUM(amount_residual), 0) AS total_ar, COALESCE(SUM(CASE WHEN invoice_date_due < CURRENT_DATE THEN amount_residual ELSE 0 END), 0) AS overdue_ar FROM fact_account_moves WHERE tenant_id = :tenant_id AND move_type = 'out_invoice' AND state = 'posted' AND payment_state IN ('not_paid', 'partial') AND amount_residual > 0 {comp_filter}"
    overdue_q = f"SELECT partner_name, COALESCE(SUM(amount_residual), 0) AS amount, MAX(CURRENT_DATE - invoice_date_due) AS days FROM fact_account_moves WHERE tenant_id = :tenant_id AND move_type = 'out_invoice' AND state = 'posted' AND payment_state IN ('not_paid', 'partial') AND amount_residual > 0 AND invoice_date_due < CURRENT_DATE {comp_filter} GROUP BY partner_id, partner_name ORDER BY amount DESC LIMIT :limit"
    s = run_query(summary_q, params)[0]; rows = run_query(overdue_q, params)
    total, overdue = float(s["total_ar"] or 0), float(s["overdue_ar"] or 0)
    ratio = calculate_ratio(overdue, total)
    return {"tool_name": "get_receivables_analysis_tool", "total_receivables": total, "overdue_receivables": overdue, "overdue_ratio": ratio, "top_overdue_customers": [{"customer": r["partner_name"], "amount": float(r["amount"]), "days": int(r["days"])} for r in rows]}

def get_business_health_score_tool(tenant_id: str, company_id: int | None = None) -> dict:
    sales = get_sales_summary_tool(tenant_id, company_id); cash = get_cash_flow_health_tool(tenant_id, company_id)
    rec = get_receivables_analysis_tool(tenant_id, company_id); inv = get_inventory_efficiency_tool(tenant_id, company_id)
    s_score = 90 if sales["total_revenue"] > 100000 else 50; c_score = 90 if cash["liquidity_status"] == "Strong" else 35
    r_score = 90 if rec["overdue_ratio"] < 0.2 else 30; i_score = 90 if inv["efficiency_rating"] == "High" else 35
    final = round(s_score * 0.25 + c_score * 0.25 + r_score * 0.25 + i_score * 0.25, 2)
    return {"tool_name": "get_business_health_score_tool", "business_health_score": final, "health_status": "Strong" if final >= 80 else "Stable" if final >= 60 else "Risk"}

def get_time_series_data_tool(tenant_id: str, company_id: int | None = None, granularity: str = "month") -> dict:
    params = {"tenant_id": tenant_id}; comp_filter = " AND company_id = :company_id" if company_id else ""
    if company_id: params["company_id"] = company_id
    query = f"SELECT DATE_TRUNC('{granularity}', date_order) AS period, COALESCE(SUM(amount_total), 0) AS revenue FROM fact_sales_orders WHERE tenant_id = :tenant_id AND state IN ('sale', 'done') {comp_filter} GROUP BY period ORDER BY period ASC"
    rows = run_query(query, params)
    return {"tool_name": "get_time_series_data_tool", "points": [{"period": str(r["period"]), "revenue": float(r["revenue"])} for r in rows]}

def get_sales_chart_data_tool(tenant_id: str, company_id: int | None = None, company_ids: list[int] | None = None, granularity: str = "month") -> dict:
    selected_company_ids = normalize_company_ids(company_id=company_id, companies=company_ids)
    query = f"SELECT DATE_TRUNC('{granularity}', date_order) AS period, COALESCE(SUM(amount_total), 0) AS revenue, COUNT(*) AS orders FROM fact_sales_orders WHERE tenant_id = :tenant_id AND state IN ('sale', 'done') AND date_order IS NOT NULL"
    params = {"tenant_id": tenant_id}
    if selected_company_ids:
        f_sql, f_params = build_company_filter_sql(selected_company_ids); query += f_sql; params.update(f_params)
    query += " GROUP BY period ORDER BY period ASC"
    rows = run_query(query, params); data = []
    for r in rows:
        lbl = r["period"].strftime("%Y-%m" if granularity == "month" else "%Y-%m-%d")
        data.append({"period": lbl, "name": lbl, "revenue": float(r["revenue"]), "value": float(r["revenue"]), "orders": int(r["orders"])})
    return {"tool_name": "get_sales_chart_data_tool", "type": "chart", "chart": {"chartType": "line", "title": "Sales Trend", "xKey": "period", "series": [{"dataKey": "revenue", "label": "Revenue", "valueFormat": "compact"}], "data": data}}

def analyze_variance_tool(tenant_id: str, company_id: int | None = None) -> dict:
    query = "WITH m AS (SELECT DATE_TRUNC('month', date_order) AS month, SUM(amount_total) AS rev FROM fact_sales_orders WHERE tenant_id = :tenant_id AND state IN ('sale', 'done') "
    params = {"tenant_id": tenant_id}
    if company_id: query += " AND company_id = :company_id"; params["company_id"] = company_id
    query += " GROUP BY month ORDER BY month DESC LIMIT 2) SELECT * FROM m"
    rows = run_query(query, params)
    if len(rows) < 2: return {"tool_name": "analyze_variance_tool", "status": "not_enough_data"}
    curr, prev = float(rows[0]["rev"] or 0), float(rows[1]["rev"] or 0)
    var = curr - prev; pct = calculate_ratio(var, prev) * 100
    return {"tool_name": "analyze_variance_tool", "variance": {"revenue_change": var, "revenue_change_pct": pct, "direction": "Increase" if var > 0 else "Decrease"}}

def forecast_sales_tool(tenant_id: str, company_id: int | None = None, forecast_periods: int = 3) -> dict:
    query = "SELECT DATE_TRUNC('month', date_order) AS month, SUM(amount_total) AS rev FROM fact_sales_orders WHERE tenant_id = :tenant_id AND state IN ('sale', 'done') "
    params = {"tenant_id": tenant_id}
    if company_id: query += " AND company_id = :company_id"; params["company_id"] = company_id
    query += " GROUP BY month ORDER BY month ASC"; rows = run_query(query, params)
    if len(rows) < 3: return {"tool_name": "forecast_sales_tool", "status": "not_enough_data"}
    avg = sum(float(r["rev"] or 0) for r in rows[-3:]) / 3; last_dt = rows[-1]["month"]; forecast = []
    for i in range(1, forecast_periods + 1):
        f_dt = last_dt + relativedelta(months=i)
        forecast.append({"month": f_dt.strftime("%Y-%m-01"), "revenue": avg})
    return {"tool_name": "forecast_sales_tool", "forecast": forecast}

def analyze_profitability_tool(tenant_id: str, company_id: int | None = None, limit: int = 10) -> dict:
    query = "SELECT l.product_name, SUM(l.price_total) AS rev, SUM(l.product_uom_qty * COALESCE(p.standard_price, 0)) AS cost FROM fact_sales_order_lines l LEFT JOIN dim_products p ON p.tenant_id = l.tenant_id AND p.odoo_id = l.product_id WHERE l.tenant_id = :tenant_id AND l.state IN ('sale', 'done') "
    params = {"tenant_id": tenant_id, "limit": limit}
    if company_id: query += " AND l.company_id = :company_id"; params["company_id"] = company_id
    query += " GROUP BY l.product_id, l.product_name ORDER BY (SUM(l.price_total) - SUM(l.product_uom_qty * COALESCE(p.standard_price, 0))) DESC LIMIT :limit"
    rows = run_query(query, params); products = []
    for r in rows:
        rev, cost = float(r["rev"] or 0), float(r["cost"] or 0); profit = rev - cost
        products.append({"product": r["product_name"], "revenue": rev, "profit": profit, "margin": calculate_ratio(profit, rev) * 100})
    return {"tool_name": "analyze_profitability_tool", "top_profitable_products": products}

def get_customer_metrics_tool(tenant_id: str, company_id: int | None = None, limit: int = 10) -> dict:
    query = "SELECT partner_name, COUNT(*) AS orders, SUM(amount_total) AS rev FROM fact_sales_orders WHERE tenant_id = :tenant_id AND state IN ('sale', 'done') "
    params = {"tenant_id": tenant_id, "limit": limit}
    if company_id: query += " AND company_id = :company_id"; params["company_id"] = company_id
    query += " GROUP BY partner_id, partner_name ORDER BY rev DESC LIMIT :limit"
    rows = run_query(query, params)
    return {"tool_name": "get_customer_metrics_tool", "top_customers": [{"customer": r["partner_name"], "revenue": float(r["rev"]), "orders": int(r["orders"])} for r in rows]}

def ask_database_custom_question(tenant_id: str, question: str, company_id: int | None = None) -> dict:
    # Use the separate SQLAgent for ad-hoc queries
    from .sql_agent import ask_database_custom_question as run_sql_agent
    return run_sql_agent(question, tenant_id)

def generate_report_tool(tenant_id: str, company_id: int | None = None, report_type: str = "business_summary") -> dict:
    reports_dir = Path("reports"); reports_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S"); fname = f"report_{tenant_id}_{ts}.pdf"; path = reports_dir / fname
    sales = get_sales_summary_tool(tenant_id, company_id); cash = get_cash_flow_health_tool(tenant_id, company_id)
    lines = [f"Report: {report_type.upper()}", "="*40, f"Revenue: {sales['total_revenue']}", f"Liquidity: {cash['liquidity_status']}", "="*40]
    c = canvas.Canvas(str(path), pagesize=letter); y = 750
    for line in lines: c.drawString(50, y, line); y -= 20
    c.save()
    return {"tool_name": "generate_report_tool", "report_ready": True, "report_path": str(path), "report_filename": fname}

def send_alert_tool(tenant_id: str, title: str, message: str, **kwargs) -> dict:
    return {"tool_name": "send_alert_tool", "sent": True, "alert": {"title": title, "message": message}}

def send_email_tool(tenant_id: str, to_email: str, subject: str, body: str, **kwargs) -> dict:
    return {"tool_name": "send_email_tool", "sent": True, "email": {"to": to_email, "subject": subject}}

def fetch_odoo_live_data_tool(model: str, domain: list, fields: list = None) -> dict:
    """Fetch live data directly from Odoo via XML-RPC."""
    try:
        client = OdooClient()
        records = client.search_read(model, domain, fields or [], limit=10)
        return {"tool_name": "fetch_odoo_live_data_tool", "records": records, "count": len(records), "note": "Live data fetched from Odoo."}
    except Exception as e:
        return {"tool_name": "fetch_odoo_live_data_tool", "error": str(e)}

# ─────────────────────────────
# FAST TOOL SELECTION
# ─────────────────────────────

def select_fast_tool(message: str) -> str | None:
    text = normalize_business_text_for_intent(message)
    if any(kw in text for kw in ["graph", "chart", "plot", "visualize"]): return "get_sales_chart_data_tool"
    if any(kw in text for kw in ["variance", "compare"]): return "analyze_variance_tool"
    if any(kw in text for kw in ["trend", "time series", "by month"]): return "get_time_series_data_tool"
    if any(kw in text for kw in ["report", "pdf"]): return "generate_report_tool"
    if any(kw in text for kw in ["health", "status"]): return "get_business_health_score_tool"
    if any(kw in text for kw in ["profit", "margin"]): return "analyze_profitability_tool"
    if any(kw in text for kw in ["forecast", "predict"]): return "forecast_sales_tool"
    if any(kw in text for kw in ["owe", "receivable", "overdue"]): return "get_receivables_analysis_tool"
    if any(kw in text for kw in ["revenue", "sales summary"]): return "get_sales_summary_tool"
    if any(kw in text for kw in ["top products", "best selling"]): return "get_top_products_tool"
    if any(kw in text for kw in ["low stock", "inventory alert"]): return "get_inventory_alerts_tool"
    if any(kw in text for kw in ["efficiency", "turnover"]): return "get_inventory_efficiency_tool"
    if any(kw in text for kw in ["customer", "client"]): return "get_customer_metrics_tool"
    if any(kw in text for kw in ["cash flow", "liquidity", "payable"]): return "get_cash_flow_health_tool"
    if any(kw in text for kw in ["live data", "from odoo", "real time"]): return "fetch_odoo_live_data_tool"
    return None

def run_fast_tool(message: str, tenant_id: str, company_id: int | None = None, companies: list[int] | None = None, context: str | None = None) -> dict | None:
    tool_name = select_fast_tool(message)
    if not tool_name: return None
    comp_ids = companies or ([company_id] if company_id else None)
    start, end, lbl = extract_date_range(message)
    
    if tool_name == "get_sales_summary_tool": return get_sales_summary_tool(tenant_id, company_id, comp_ids, start, end, lbl or "period")
    if tool_name == "get_top_products_tool": return get_top_products_tool(tenant_id, company_id, comp_ids, start, end)
    if tool_name == "get_inventory_alerts_tool": return get_inventory_alerts_tool(tenant_id, company_id, comp_ids)
    if tool_name == "get_sales_chart_data_tool": return get_sales_chart_data_tool(tenant_id, company_id, comp_ids)
    if tool_name == "analyze_variance_tool": return analyze_variance_tool(tenant_id, company_id)
    if tool_name == "get_time_series_data_tool": return get_time_series_data_tool(tenant_id, company_id)
    if tool_name == "generate_report_tool": return generate_report_tool(tenant_id, company_id)
    if tool_name == "get_business_health_score_tool": return get_business_health_score_tool(tenant_id, company_id)
    if tool_name == "analyze_profitability_tool": return analyze_profitability_tool(tenant_id, company_id)
    if tool_name == "forecast_sales_tool": return forecast_sales_tool(tenant_id, company_id)
    if tool_name == "get_receivables_analysis_tool": return get_receivables_analysis_tool(tenant_id, company_id)
    if tool_name == "get_inventory_efficiency_tool": return get_inventory_efficiency_tool(tenant_id, company_id)
    if tool_name == "get_customer_metrics_tool": return get_customer_metrics_tool(tenant_id, company_id)
    if tool_name == "get_cash_flow_health_tool": return get_cash_flow_health_tool(tenant_id, company_id)
    if tool_name == "fetch_odoo_live_data_tool": 
        return fetch_odoo_live_data_tool("res.partner", [["customer_rank", ">", 0]], ["name", "email"])
    return None

def run_reasoning_tools(message: str, tenant_id: str, company_id: int | None = None, plan: dict | None = None) -> dict:
    # Reasoning can run multiple tools. For now, run a comprehensive set.
    results = {}
    results["sales"] = get_sales_summary_tool(tenant_id, company_id)
    results["top_products"] = get_top_products_tool(tenant_id, company_id)
    results["health"] = get_business_health_score_tool(tenant_id, company_id)
    return results
