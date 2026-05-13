# api/agent/tools.py

import re
from .db import run_query
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from pathlib import Path
from datetime import datetime
from .query_context import extract_date_range, normalize_company_ids, build_company_filter_sql
from .config import AgentConfig


# ─────────────────────────────
# GRAPH DETECTION
# ─────────────────────────────

def normalize_business_text_for_intent(message: str | None) -> str:
    """
    Lightweight intent normalizer.

    Goal:
    - Fix common user typos.
    - Map natural business phrases to the internal terms our tools understand.
    - Keep the original meaning, but make routing more flexible.
    """

    text = (message or "").lower().strip()

    replacements = {
        # Common typos
        "revnue": "revenue",
        "revenu": "revenue",
        "revanue": "revenue",
        "sale summery": "sales summary",
        "sales summery": "sales summary",
        "salse": "sales",
        "seles": "sales",
        "seling": "selling",
        "inventry": "inventory",
        "inventroy": "inventory",
        "invntory": "inventory",
        "stok": "stock",
        "stcok": "stock",
        "custmer": "customer",
        "custmers": "customers",
        "costumer": "customer",
        "costumers": "customers",
        "prodcut": "product",
        "prodcuts": "products",
        "prduct": "product",
        "prducts": "products",
        "grph": "graph",
        "grahp": "graph",
        "char": "chart",
        "chrt": "chart",
        "reprt": "report",
        "repport": "report",
        "pdfs": "pdf",

        # Natural sales phrases
        "how much we sell": "sales summary",
        "how much did we sell": "sales summary",
        "how much have we sold": "sales summary",
        "what did we sell": "sales summary",
        "what we sold": "sales summary",
        "sales amount": "sales summary",
        "selling amount": "sales summary",

        # Report / PDF phrases
        "pdf for": "pdf report for",
        "as pdf": "pdf report",
        "in pdf": "pdf report",
        "pdf version": "pdf report",
        "download pdf": "download report",
        "export pdf": "download report",
        "export as pdf": "download report",
        "make pdf": "generate report",
        "make a pdf": "generate report",
        "i want a pdf": "generate report",
        "i need a pdf": "generate report",
        "report for": "generate report for",
        "make report": "generate report",
        "make a report": "generate report",

        # Inventory natural phrases
        "almost finished": "low stock",
        "nearly finished": "low stock",
        "nearly empty": "low stock",
        "almost empty": "low stock",
        "few quantity": "low stock",
        "little quantity": "low stock",
        "not enough stock": "low stock",
        "stock problem": "inventory alerts",
        "stock problems": "inventory alerts",
        "inventory problem": "inventory alerts",
        "inventory problems": "inventory alerts",
        "inventory issue": "inventory alerts",
        "inventory issues": "inventory alerts",
        "what should we reorder": "low stock reorder",
        "reorder first": "low stock reorder",
        "give me reorder recommendations": "low stock reorder recommendations",
        "reorder recommendations": "low stock reorder recommendations",
        "reorder items": "low stock reorder items",
        "items to reorder": "low stock reorder items",
        "products to reorder": "low stock reorder products",
        "buy again": "low stock reorder",

        # Expiry / lots natural phrases
        "which lots will expire soon": "show expiring lots",
        "lots will expire soon": "show expiring lots",
        "lots expire soon": "show expiring lots",
        "expire soon": "expiring lots",
        "expiry": "expiration",
        "near expiry": "expiring lots",
        "expiration alerts": "expiring lots",

        # Inventory report phrases
        "generate inventory report": "generate report inventory",
        "inventory report": "generate report inventory",
        "download inventory report": "download report inventory",
        "pdf inventory": "pdf report inventory",
        "pdf for inventory": "pdf report inventory",

        # Customer/product natural phrases
        "best clients": "top customers",
        "top clients": "top customers",
        "biggest clients": "top customers",
        "best customers": "top customers",
        "biggest customers": "top customers",
        "best items": "top products",
        "top items": "top products",
        "best selling items": "best selling products",
        "most sold items": "most sold products",

        # Graph natural phrases
        "draw": "chart",
        "plot": "chart",
        "visualize": "chart",
        "visualise": "chart",
    }

    # Do phrase replacements first
    for wrong, correct in replacements.items():
        text = text.replace(wrong, correct)

    # Normalize spacing
    text = " ".join(text.split())
    return text



def is_graph_request(text: str) -> bool:
    text = normalize_business_text_for_intent(text)

    has_keywords = (
        "plot" in text
        or "graph" in text
        or "chart" in text
        or "visualize" in text
    )

    has_structured_data = bool(
        re.search(r"\d+\s*[:\-]\s*\d+", text)
    )

    return has_keywords or has_structured_data


# ─────────────────────────────
# GRAPH DATA EXTRACTION
# ─────────────────────────────
def extract_graph_data(text: str) -> dict:
    """
    Extract graph data from formats like:
    1:1000, 2:1500, 3:2300
    """

    pairs = re.findall(r"(\d+)\s*[:\-]\s*(\d+)", text)

    if pairs:
        x = [int(a) for a, _ in pairs]
        y = [int(b) for _, b in pairs]

        return {
            "x": x,
            "y": y,
            "points": [
                {"x": x_val, "y": y_val}
                for x_val, y_val in zip(x, y)
            ],
        }

    numbers = list(map(int, re.findall(r"\d+", text)))

    if len(numbers) >= 2:
        x = list(range(1, len(numbers) + 1))
        y = numbers

        return {
            "x": x,
            "y": y,
            "points": [
                {"x": x_val, "y": y_val}
                for x_val, y_val in zip(x, y)
            ],
        }

    return {
        "x": [],
        "y": [],
        "points": [],
    }


# ─────────────────────────────
# PDF DETECTION
# ─────────────────────────────
def is_pdf_request(text: str) -> bool:
    text = text.lower()

    pdf_keywords = [
        "pdf",
        "generate pdf",
        "save as pdf",
        "pdf report",
        "generate a pdf report",
    ]

    return any(keyword in text for keyword in pdf_keywords)


# ─────────────────────────────
# PDF GENERATION
# ─────────────────────────────
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


# ─────────────────────────────
# SIMPLE CALCULATOR HELPER
# ─────────────────────────────
def calculate_ratio(numerator: float, denominator: float) -> float:
    if denominator == 0:
        return 0.0

    return numerator / denominator


def calculate_ratio_tool(numerator: float, denominator: float) -> dict:
    ratio = calculate_ratio(numerator, denominator)

    return {
        "tool_name": "calculate_ratio_tool",
        "numerator": numerator,
        "denominator": denominator,
        "ratio": ratio,
        "percentage": ratio * 100,
    }


# ─────────────────────────────
# BUSINESS TOOL MOCK DATA
# IMPORTANT:
# These are temporary mock tools.
# Later we will replace the data with real DB/API queries.
# ─────────────────────────────
def get_sales_summary_tool(
    tenant_id: str,
    company_id: int | None = None,
    company_ids: list[int] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    period: str = "selected_period",
) -> dict:
    """
    Real sales summary from PostgreSQL fact_sales_orders.
    Supports selected companies and optional date range.
    """

    selected_company_ids = normalize_company_ids(
        company_id=company_id,
        companies=company_ids,
    )

    query = """
    SELECT
        COALESCE(SUM(amount_total), 0) AS total_revenue,
        COUNT(*) AS order_count,
        COALESCE(AVG(amount_total), 0) AS average_order_value,
        COALESCE(MIN(date_order), NULL) AS first_order_date,
        COALESCE(MAX(date_order), NULL) AS last_order_date
    FROM fact_sales_orders
    WHERE tenant_id = :tenant_id
      AND state IN ('sale', 'done')
    """

    params = {
        "tenant_id": tenant_id,
    }

    if selected_company_ids:
        placeholders = []
        for index, cid in enumerate(selected_company_ids):
            key = f"company_{index}"
            placeholders.append(f":{key}")
            params[key] = cid
        query += f" AND company_id IN ({', '.join(placeholders)})"

    if start_date:
        query += " AND date_order >= :start_date"
        params["start_date"] = start_date

    if end_date:
        query += " AND date_order <= :end_date"
        params["end_date"] = end_date

    rows = run_query(query, params)
    row = rows[0] if rows else {}

    total_revenue = float(row.get("total_revenue") or 0)
    order_count = int(row.get("order_count") or 0)
    average_order_value = float(row.get("average_order_value") or 0)

    return {
        "tool_name": "get_sales_summary_tool",
        "tenant_id": tenant_id,
        "company_id": company_id,
        "company_ids": selected_company_ids,
        "start_date": start_date,
        "end_date": end_date,
        "period": period,
        "currency": "unknown",
        "total_revenue": total_revenue,
        "order_count": order_count,
        "average_order_value": average_order_value,
        "gross_margin_pct": None,
        "first_order_date": str(row.get("first_order_date")) if row.get("first_order_date") else None,
        "last_order_date": str(row.get("last_order_date")) if row.get("last_order_date") else None,
        "note": "Real data from PostgreSQL fact_sales_orders. Only confirmed sales states are included: sale, done.",
    }

def get_top_products_tool(
    tenant_id: str,
    company_id: int | None = None,
    company_ids: list[int] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 10,
) -> dict:
    """
    Real top products from PostgreSQL fact_sales_order_lines + fact_sales_orders.
    Supports selected companies and optional date range.
    """

    selected_company_ids = normalize_company_ids(
        company_id=company_id,
        companies=company_ids,
    )

    query = """
    SELECT
        l.product_id,
        l.product_name,
        COALESCE(SUM(l.product_uom_qty), 0) AS quantity,
        COALESCE(SUM(l.price_total), 0) AS revenue
    FROM fact_sales_order_lines l
    JOIN fact_sales_orders o
      ON o.id = l.sales_order_id
     AND o.tenant_id = l.tenant_id
    WHERE l.tenant_id = :tenant_id
      AND l.state IN ('sale', 'done')
      AND o.state IN ('sale', 'done')
      AND l.product_id IS NOT NULL
    """

    params = {
        "tenant_id": tenant_id,
        "limit": limit,
    }

    if selected_company_ids:
        placeholders = []
        for index, cid in enumerate(selected_company_ids):
            key = f"company_{index}"
            placeholders.append(f":{key}")
            params[key] = cid
        query += f" AND l.company_id IN ({', '.join(placeholders)})"

    if start_date:
        query += " AND o.date_order >= :start_date"
        params["start_date"] = start_date

    if end_date:
        # inclusive whole day
        query += " AND o.date_order < (CAST(:end_date AS date) + INTERVAL '1 day')"
        params["end_date"] = end_date

    query += """
    GROUP BY l.product_id, l.product_name
    ORDER BY revenue DESC
    LIMIT :limit
    """

    rows = run_query(query, params)

    products = []
    for row in rows:
        products.append(
            {
                "product_id": row.get("product_id"),
                "product": row.get("product_name"),
                "revenue": float(row.get("revenue") or 0),
                "quantity": float(row.get("quantity") or 0),
            }
        )

    return {
        "tool_name": "get_top_products_tool",
        "tenant_id": tenant_id,
        "company_id": company_id,
        "company_ids": selected_company_ids,
        "start_date": start_date,
        "end_date": end_date,
        "limit": limit,
        "currency": "unknown",
        "products": products,
        "note": "Real data from PostgreSQL fact_sales_order_lines joined to fact_sales_orders. Only confirmed sales states are included: sale, done.",
    }

def get_inventory_alerts_tool(
    tenant_id: str,
    company_id: int | None = None,
    company_ids: list[int] | None = None,
    low_stock_threshold: float = 10,
    expiring_days: int = 90,
) -> dict:
    """
    Real inventory alerts from PostgreSQL:
    - Low stock from fact_inventory_quants
    - Expiring lots from dim_lots
    Supports selected companies.
    """

    selected_company_ids = normalize_company_ids(
        company_id=company_id,
        companies=company_ids,
    )

    params = {
        "tenant_id": tenant_id,
        "threshold": low_stock_threshold,
        "expiring_days": expiring_days,
    }

    company_filter = ""
    if selected_company_ids:
        placeholders = []
        for index, cid in enumerate(selected_company_ids):
            key = f"company_{index}"
            placeholders.append(f":{key}")
            params[key] = cid
        company_filter = f" AND company_id IN ({', '.join(placeholders)})"

    low_stock_query = f"""
    SELECT
        product_id,
        product_name,
        product_code,
        location_id,
        location_name,
        company_id,
        company_name,
        COALESCE(SUM(available_quantity), 0) AS available,
        COALESCE(SUM(quantity), 0) AS quantity,
        COALESCE(SUM(reserved_quantity), 0) AS reserved_quantity
    FROM fact_inventory_quants
    WHERE tenant_id = :tenant_id
      AND product_id IS NOT NULL
      {company_filter}
    GROUP BY
        product_id,
        product_name,
        product_code,
        location_id,
        location_name,
        company_id,
        company_name
    HAVING
        COALESCE(SUM(available_quantity), 0) > 0
        AND COALESCE(SUM(available_quantity), 0) <= :threshold
    ORDER BY available ASC
    LIMIT 25
    """

    expiring_query = f"""
    SELECT
        id,
        odoo_id,
        name,
        ref,
        product_id,
        product_name,
        expiration_date,
        use_date,
        removal_date,
        alert_date,
        company_id,
        company_name
    FROM dim_lots
    WHERE tenant_id = :tenant_id
      AND expiration_date IS NOT NULL
      AND expiration_date >= CURRENT_DATE
      AND expiration_date < (CURRENT_DATE + (:expiring_days * INTERVAL '1 day'))
      {company_filter}
    ORDER BY expiration_date ASC
    LIMIT 25
    """

    low_stock_rows = run_query(low_stock_query, params)
    expiring_rows = run_query(expiring_query, params)

    low_stock_items = []
    for row in low_stock_rows:
        low_stock_items.append(
            {
                "product_id": row.get("product_id"),
                "product": row.get("product_name"),
                "product_code": row.get("product_code"),
                "available": float(row.get("available") or 0),
                "quantity": float(row.get("quantity") or 0),
                "reserved_quantity": float(row.get("reserved_quantity") or 0),
                "threshold": low_stock_threshold,
                "location_id": row.get("location_id"),
                "location": row.get("location_name"),
                "company_id": row.get("company_id"),
                "company": row.get("company_name"),
            }
        )

    expiring_soon = []
    for row in expiring_rows:
        expiring_soon.append(
            {
                "lot_id": row.get("id"),
                "odoo_id": row.get("odoo_id"),
                "lot": row.get("name"),
                "ref": row.get("ref") or row.get("name"),
                "product_id": row.get("product_id"),
                "product": row.get("product_name"),
                "expiration_date": str(row.get("expiration_date")) if row.get("expiration_date") else None,
                "use_date": str(row.get("use_date")) if row.get("use_date") else None,
                "removal_date": str(row.get("removal_date")) if row.get("removal_date") else None,
                "alert_date": str(row.get("alert_date")) if row.get("alert_date") else None,
                "company_id": row.get("company_id"),
                "company": row.get("company_name"),
            }
        )

    return {
        "tool_name": "get_inventory_alerts_tool",
        "tenant_id": tenant_id,
        "company_id": company_id,
        "company_ids": selected_company_ids,
        "low_stock_threshold": low_stock_threshold,
        "low_stock_count": len(low_stock_items),
        "expiring_days": expiring_days,
        "expiring_soon_count": len(expiring_soon),
        "low_stock_items": low_stock_items,
        "expiring_soon": expiring_soon,
        "note": (
            "Real data from PostgreSQL fact_inventory_quants and dim_lots. "
            "Low stock uses available_quantity <= threshold. Expiring lots use expiration_date within the selected window."
        ),
    }

def get_inventory_efficiency_tool(
    tenant_id: str,
    company_id: int | None = None,
    company_ids: list[int] | None = None,
) -> dict:
    """
    Real inventory efficiency from PostgreSQL.
    Uses fact_inventory_quants, dim_products, and fact_inventory_moves.
    Supports selected companies.
    """

    selected_company_ids = normalize_company_ids(
        company_id=company_id,
        companies=company_ids,
    )

    params = {"tenant_id": tenant_id}

    quant_company_filter = ""
    move_company_filter = ""

    if selected_company_ids:
        quant_placeholders = []
        move_placeholders = []

        for index, cid in enumerate(selected_company_ids):
            q_key = f"q_company_{index}"
            m_key = f"m_company_{index}"
            quant_placeholders.append(f":{q_key}")
            move_placeholders.append(f":{m_key}")
            params[q_key] = cid
            params[m_key] = cid

        quant_company_filter = f" AND q.company_id IN ({', '.join(quant_placeholders)})"
        move_company_filter = f" AND m.company_id IN ({', '.join(move_placeholders)})"

    inventory_value_query = f"""
    SELECT
        COALESCE(SUM(q.available_quantity * COALESCE(p.standard_price, 0)), 0) AS total_inventory_value,
        COUNT(DISTINCT q.product_id) AS total_sku_count,
        COALESCE(SUM(q.available_quantity), 0) AS total_available_quantity,
        COALESCE(SUM(q.quantity), 0) AS total_on_hand_quantity,
        COALESCE(SUM(q.reserved_quantity), 0) AS total_reserved_quantity
    FROM fact_inventory_quants q
    LEFT JOIN dim_products p
        ON p.tenant_id = q.tenant_id
       AND p.odoo_id = q.product_id
    WHERE q.tenant_id = :tenant_id
      AND q.available_quantity > 0
      {quant_company_filter}
    """

    movement_query = f"""
    SELECT
        COUNT(*) AS stock_move_count_12m,
        COALESCE(SUM(m.quantity_done), 0) AS total_quantity_moved_12m,
        COALESCE(SUM(m.quantity_done * COALESCE(p.standard_price, 0)), 0) AS movement_value_12m
    FROM fact_inventory_moves m
    LEFT JOIN dim_products p
        ON p.tenant_id = m.tenant_id
       AND p.odoo_id = m.product_id
    WHERE m.tenant_id = :tenant_id
      AND m.state = 'done'
      AND m.date >= CURRENT_DATE - INTERVAL '12 months'
      {move_company_filter}
    """

    inventory_rows = run_query(inventory_value_query, params)
    movement_rows = run_query(movement_query, params)

    inventory = inventory_rows[0] if inventory_rows else {}
    movement = movement_rows[0] if movement_rows else {}

    total_inventory_value = float(inventory.get("total_inventory_value") or 0)
    total_sku_count = int(inventory.get("total_sku_count") or 0)
    total_available_quantity = float(inventory.get("total_available_quantity") or 0)
    total_on_hand_quantity = float(inventory.get("total_on_hand_quantity") or 0)
    total_reserved_quantity = float(inventory.get("total_reserved_quantity") or 0)

    stock_move_count_12m = int(movement.get("stock_move_count_12m") or 0)
    total_quantity_moved_12m = float(movement.get("total_quantity_moved_12m") or 0)
    movement_value_12m = float(movement.get("movement_value_12m") or 0)

    turnover_ratio = calculate_ratio(movement_value_12m, total_inventory_value)

    if turnover_ratio > 0:
        days_inventory_on_hand = 365 / turnover_ratio
    else:
        days_inventory_on_hand = None

    if turnover_ratio > 6:
        efficiency_rating = "High"
    elif turnover_ratio >= 3:
        efficiency_rating = "Medium"
    else:
        efficiency_rating = "Low"

    return {
        "tool_name": "get_inventory_efficiency_tool",
        "tenant_id": tenant_id,
        "company_id": company_id,
        "company_ids": selected_company_ids,
        "currency": "unknown",
        "total_inventory_value": total_inventory_value,
        "total_sku_count": total_sku_count,
        "total_available_quantity": total_available_quantity,
        "total_on_hand_quantity": total_on_hand_quantity,
        "total_reserved_quantity": total_reserved_quantity,
        "stock_move_count_12m": stock_move_count_12m,
        "total_quantity_moved_12m": total_quantity_moved_12m,
        "movement_value_12m": movement_value_12m,
        "turnover_ratio": turnover_ratio,
        "days_inventory_on_hand": days_inventory_on_hand,
        "efficiency_rating": efficiency_rating,
        "note": (
            "Real data from PostgreSQL. Inventory value uses fact_inventory_quants × dim_products.standard_price. "
            "Turnover uses done inventory moves from fact_inventory_moves over the last 12 months."
        ),
    }

def get_business_health_score_tool(
    tenant_id: str,
    company_id: int | None = None,
) -> dict:
    """
    Real business health score from PostgreSQL-backed tools.

    Combines:
    - Sales summary
    - Cash flow health
    - Receivables analysis
    - Inventory efficiency
    - Inventory alerts

    Score:
    0 to 100
    """

    sales = get_sales_summary_tool(
        tenant_id=tenant_id,
        company_id=company_id,
    )

    cash_flow = get_cash_flow_health_tool(
        tenant_id=tenant_id,
        company_id=company_id,
    )

    receivables = get_receivables_analysis_tool(
        tenant_id=tenant_id,
        company_id=company_id,
    )

    inventory_efficiency = get_inventory_efficiency_tool(
        tenant_id=tenant_id,
        company_id=company_id,
    )

    inventory_alerts = get_inventory_alerts_tool(
        tenant_id=tenant_id,
        company_id=company_id,
    )

    # ─────────────────────────────
    # 1. Sales score
    # ─────────────────────────────
    total_revenue = sales.get("total_revenue", 0) or 0
    order_count = sales.get("order_count", 0) or 0

    if total_revenue > 0 and order_count >= 20:
        sales_score = 90
    elif total_revenue > 0 and order_count >= 5:
        sales_score = 70
    elif total_revenue > 0:
        sales_score = 50
    else:
        sales_score = 20

    # ─────────────────────────────
    # 2. Cash flow score
    # ─────────────────────────────
    liquidity_status = cash_flow.get("liquidity_status", "Risk")

    if liquidity_status == "Strong":
        cash_flow_score = 90
    elif liquidity_status == "Stable":
        cash_flow_score = 70
    else:
        cash_flow_score = 35

    # ─────────────────────────────
    # 3. Receivables score
    # ─────────────────────────────
    overdue_ratio = receivables.get("overdue_ratio", 0) or 0

    if overdue_ratio < 0.2:
        receivables_score = 90
    elif overdue_ratio < 0.5:
        receivables_score = 60
    else:
        receivables_score = 30

    # ─────────────────────────────
    # 4. Inventory efficiency score
    # ─────────────────────────────
    efficiency_rating = inventory_efficiency.get("efficiency_rating", "Low")

    if efficiency_rating == "High":
        inventory_efficiency_score = 90
    elif efficiency_rating == "Medium":
        inventory_efficiency_score = 65
    else:
        inventory_efficiency_score = 35

    # ─────────────────────────────
    # 5. Inventory alert score
    # ─────────────────────────────
    low_stock_items = inventory_alerts.get("low_stock_items", []) or []
    low_stock_count = len(low_stock_items)

    if low_stock_count == 0:
        inventory_alert_score = 90
    elif low_stock_count <= 5:
        inventory_alert_score = 70
    elif low_stock_count <= 20:
        inventory_alert_score = 50
    else:
        inventory_alert_score = 30

    # ─────────────────────────────
    # Weighted final score
    # ─────────────────────────────
    final_score = (
        sales_score * 0.20
        + cash_flow_score * 0.25
        + receivables_score * 0.25
        + inventory_efficiency_score * 0.15
        + inventory_alert_score * 0.15
    )

    final_score = round(final_score, 2)

    if final_score >= 80:
        health_status = "Strong"
    elif final_score >= 60:
        health_status = "Stable"
    elif final_score >= 40:
        health_status = "Watch"
    else:
        health_status = "Risk"

    return {
        "tool_name": "get_business_health_score_tool",
        "tenant_id": tenant_id,
        "company_id": company_id,
        "business_health_score": final_score,
        "health_status": health_status,
        "component_scores": {
            "sales_score": sales_score,
            "cash_flow_score": cash_flow_score,
            "receivables_score": receivables_score,
            "inventory_efficiency_score": inventory_efficiency_score,
            "inventory_alert_score": inventory_alert_score,
        },
        "key_metrics": {
            "total_revenue": total_revenue,
            "order_count": order_count,
            "liquidity_status": liquidity_status,
            "overdue_ratio_pct": receivables.get("overdue_ratio_pct"),
            "inventory_turnover_ratio": inventory_efficiency.get("turnover_ratio"),
            "days_inventory_on_hand": inventory_efficiency.get("days_inventory_on_hand"),
            "low_stock_count": low_stock_count,
        },
        "data_sources_used": [
            "get_sales_summary_tool",
            "get_cash_flow_health_tool",
            "get_receivables_analysis_tool",
            "get_inventory_efficiency_tool",
            "get_inventory_alerts_tool",
        ],
        "note": "Real score calculated from PostgreSQL-backed tools using Odoo-synced data.",
    }








def get_cash_flow_health_tool(
    tenant_id: str,
    company_id: int | None = None,
) -> dict:
    """
    Real cash flow health from PostgreSQL fact_account_moves.

    AR = unpaid customer invoices.
    AP = unpaid vendor bills.
    """

    ar_query = """
    SELECT
        COALESCE(SUM(amount_residual), 0) AS accounts_receivable
    FROM fact_account_moves
    WHERE tenant_id = :tenant_id
      AND move_type = 'out_invoice'
      AND state = 'posted'
      AND payment_state IN ('not_paid', 'partial')
      AND amount_residual > 0
    """

    ap_query = """
    SELECT
        COALESCE(SUM(amount_residual), 0) AS accounts_payable
    FROM fact_account_moves
    WHERE tenant_id = :tenant_id
      AND move_type = 'in_invoice'
      AND state = 'posted'
      AND payment_state IN ('not_paid', 'partial')
      AND amount_residual > 0
    """

    params = {"tenant_id": tenant_id}

    if company_id is not None:
        ar_query += " AND company_id = :company_id"
        ap_query += " AND company_id = :company_id"
        params["company_id"] = company_id

    ar_rows = run_query(ar_query, params)
    ap_rows = run_query(ap_query, params)

    accounts_receivable = float(ar_rows[0].get("accounts_receivable") or 0)
    accounts_payable = float(ap_rows[0].get("accounts_payable") or 0)

    liquidity_ratio = calculate_ratio(accounts_receivable, accounts_payable)

    if accounts_payable == 0 and accounts_receivable > 0:
        status = "Strong"
    elif liquidity_ratio >= 1.5:
        status = "Strong"
    elif liquidity_ratio >= 1.0:
        status = "Stable"
    else:
        status = "Risk"

    return {
        "tool_name": "get_cash_flow_health_tool",
        "tenant_id": tenant_id,
        "company_id": company_id,
        "currency": "unknown",
        "accounts_receivable": accounts_receivable,
        "accounts_payable": accounts_payable,
        "liquidity_ratio": liquidity_ratio,
        "liquidity_status": status,
        "note": "Real data from PostgreSQL fact_account_moves. AR uses unpaid customer invoices; AP uses unpaid vendor bills.",
    }



def get_receivables_analysis_tool(
    tenant_id: str,
    company_id: int | None = None,
    limit: int = 10,
) -> dict:
    """
    Real receivables analysis from PostgreSQL fact_account_moves.

    AR logic:
    - move_type = out_invoice
    - state = posted
    - payment_state in not_paid / partial
    - amount_residual > 0

    Overdue logic:
    - invoice_date_due < CURRENT_DATE
    """

    base_where = """
    WHERE tenant_id = :tenant_id
      AND move_type = 'out_invoice'
      AND state = 'posted'
      AND payment_state IN ('not_paid', 'partial')
      AND amount_residual > 0
    """

    params = {
        "tenant_id": tenant_id,
        "limit": limit,
    }

    if company_id is not None:
        base_where += " AND company_id = :company_id"
        params["company_id"] = company_id

    summary_query = f"""
    SELECT
        COALESCE(SUM(amount_residual), 0) AS total_receivables,
        COALESCE(SUM(
            CASE
                WHEN invoice_date_due IS NOT NULL
                 AND invoice_date_due < CURRENT_DATE
                THEN amount_residual
                ELSE 0
            END
        ), 0) AS overdue_receivables,
        COUNT(*) AS open_invoice_count,
        COUNT(
            CASE
                WHEN invoice_date_due IS NOT NULL
                 AND invoice_date_due < CURRENT_DATE
                THEN 1
            END
        ) AS overdue_invoice_count
    FROM fact_account_moves
    {base_where}
    """

    top_overdue_query = f"""
    SELECT
        partner_id,
        partner_name,
        company_id,
        company_name,
        COUNT(*) AS overdue_invoice_count,
        COALESCE(SUM(amount_residual), 0) AS overdue_amount,
        MAX(CURRENT_DATE - invoice_date_due) AS max_days_overdue
    FROM fact_account_moves
    {base_where}
      AND invoice_date_due IS NOT NULL
      AND invoice_date_due < CURRENT_DATE
    GROUP BY
        partner_id,
        partner_name,
        company_id,
        company_name
    ORDER BY overdue_amount DESC
    LIMIT :limit
    """

    summary_rows = run_query(summary_query, params)
    overdue_rows = run_query(top_overdue_query, params)

    summary = summary_rows[0] if summary_rows else {}

    total_receivables = float(summary.get("total_receivables") or 0)
    overdue_receivables = float(summary.get("overdue_receivables") or 0)
    open_invoice_count = int(summary.get("open_invoice_count") or 0)
    overdue_invoice_count = int(summary.get("overdue_invoice_count") or 0)

    overdue_ratio = calculate_ratio(overdue_receivables, total_receivables)

    top_overdue_customers = []

    for row in overdue_rows:
        top_overdue_customers.append(
            {
                "partner_id": row.get("partner_id"),
                "customer": row.get("partner_name"),
                "company_id": row.get("company_id"),
                "company": row.get("company_name"),
                "overdue_invoice_count": int(row.get("overdue_invoice_count") or 0),
                "overdue_amount": float(row.get("overdue_amount") or 0),
                "max_days_overdue": int(row.get("max_days_overdue") or 0),
            }
        )

    if overdue_ratio >= 0.5:
        risk_level = "High"
    elif overdue_ratio >= 0.2:
        risk_level = "Medium"
    else:
        risk_level = "Low"

    return {
        "tool_name": "get_receivables_analysis_tool",
        "tenant_id": tenant_id,
        "company_id": company_id,
        "currency": "unknown",
        "total_receivables": total_receivables,
        "overdue_receivables": overdue_receivables,
        "open_invoice_count": open_invoice_count,
        "overdue_invoice_count": overdue_invoice_count,
        "overdue_ratio": overdue_ratio,
        "overdue_ratio_pct": overdue_ratio * 100,
        "risk_level": risk_level,
        "top_overdue_customers": top_overdue_customers,
        "note": (
            "Real data from PostgreSQL fact_account_moves. "
            "Receivables use unpaid/partial posted customer invoices."
        ),
    }


def get_time_series_data_tool(
    tenant_id: str,
    company_id: int | None = None,
    granularity: str = "month",
) -> dict:
    """
    Real revenue trend from PostgreSQL fact_sales_orders.

    Uses confirmed sales only:
    state IN ('sale', 'done')
    """

    allowed_granularities = ["day", "week", "month"]

    if granularity not in allowed_granularities:
        granularity = "month"

    query = f"""
    SELECT
        DATE_TRUNC('{granularity}', date_order) AS period,
        COALESCE(SUM(amount_total), 0) AS revenue,
        COUNT(*) AS order_count,
        COALESCE(AVG(amount_total), 0) AS average_order_value
    FROM fact_sales_orders
    WHERE tenant_id = :tenant_id
      AND state IN ('sale', 'done')
      AND date_order IS NOT NULL
    """

    params = {
        "tenant_id": tenant_id,
    }

    if company_id is not None:
        query += " AND company_id = :company_id"
        params["company_id"] = company_id

    query += """
    GROUP BY period
    ORDER BY period ASC
    """

    rows = run_query(query, params)

    points = []

    for row in rows:
        points.append(
            {
                "period": str(row.get("period")),
                "revenue": float(row.get("revenue") or 0),
                "order_count": int(row.get("order_count") or 0),
                "average_order_value": float(row.get("average_order_value") or 0),
            }
        )

    return {
        "tool_name": "get_time_series_data_tool",
        "tenant_id": tenant_id,
        "company_id": company_id,
        "granularity": granularity,
        "currency": "unknown",
        "points": points,
        "note": "Real data from PostgreSQL fact_sales_orders. Only confirmed sales states are included: sale, done.",
    }

def get_sales_chart_data_tool(
    tenant_id: str,
    company_id: int | None = None,
    company_ids: list[int] | None = None,
    granularity: str = "month",
) -> dict:
    """
    Return chart-ready JSON for sales revenue.

    Reads confirmed sales from PostgreSQL and groups by day/week/month.
    Supports default selected companies.
    """

    allowed_granularities = ["day", "week", "month"]

    if granularity not in allowed_granularities:
        granularity = "month"

    selected_company_ids = normalize_company_ids(
        company_id=company_id,
        companies=company_ids,
    )

    query = f"""
    SELECT
        DATE_TRUNC('{granularity}', date_order) AS period,
        COALESCE(SUM(amount_total), 0) AS revenue,
        COUNT(*) AS order_count,
        COALESCE(AVG(amount_total), 0) AS average_order_value
    FROM fact_sales_orders
    WHERE tenant_id = :tenant_id
      AND state IN ('sale', 'done')
      AND date_order IS NOT NULL
    """

    params = {"tenant_id": tenant_id}

    if selected_company_ids:
        placeholders = []
        for index, cid in enumerate(selected_company_ids):
            key = f"company_{index}"
            placeholders.append(f":{key}")
            params[key] = cid
        query += f" AND company_id IN ({', '.join(placeholders)})"

    query += f"""
    GROUP BY DATE_TRUNC('{granularity}', date_order)
    ORDER BY DATE_TRUNC('{granularity}', date_order) ASC
    """

    rows = run_query(query, params)

    data = []

    for row in rows:
        period_value = row.get("period")

        if period_value is None:
            period_label = "Unknown"
        elif granularity == "month":
            period_label = (
                period_value.strftime("%Y-%m")
                if hasattr(period_value, "strftime")
                else str(period_value)[:7]
            )
        else:
            period_label = (
                period_value.strftime("%Y-%m-%d")
                if hasattr(period_value, "strftime")
                else str(period_value)[:10]
            )

        data.append(
            {
                "period": period_label,
                "name": period_label,
                "revenue": float(row.get("revenue") or 0),
                "value": float(row.get("revenue") or 0),
                "order_count": int(row.get("order_count") or 0),
                "average_order_value": float(row.get("average_order_value") or 0),
            }
        )

    return {
        "tool_name": "get_sales_chart_data_tool",
        "tenant_id": tenant_id,
        "company_id": company_id,
        "company_ids": selected_company_ids,
        "response_type": "chart",
        "type": "chart",
        "message": "Here is the sales revenue chart based on confirmed sales orders.",
        "chart": {
            "chartType": "line",
            "title": "Sales Revenue Trend",
            "description": "Revenue trend from confirmed sales orders in PostgreSQL.",
            "xKey": "period",
            "series": [
                {
                    "dataKey": "revenue",
                    "label": "Revenue",
                    "valueFormat": "compact"
                },
                {
                    "dataKey": "order_count",
                    "label": "Orders",
                    "valueFormat": "integer"
                }
            ],
            "data": data,
        },
        "data": data,
        "note": "Real data from PostgreSQL fact_sales_orders. Only confirmed sales states are included: sale, done.",
    }

def analyze_variance_tool(
    tenant_id: str,
    company_id: int | None = None,
) -> dict:
    """
    Real month-over-month sales variance from PostgreSQL fact_sales_orders.

    Compares the latest synced sales month with the previous sales month.
    Uses confirmed sales only: state IN ('sale', 'done')
    """

    query = """
    WITH monthly_sales AS (
        SELECTdef select_fast_tool(message: str) -> str | None:
            DATE_TRUNC('month', date_order) AS month,
            COALESCE(SUM(amount_total), 0) AS revenue,
            COUNT(*) AS order_count,
            COALESCE(AVG(amount_total), 0) AS average_order_value
        FROM fact_sales_orders
        WHERE tenant_id = :tenant_id
          AND state IN ('sale', 'done')
          AND date_order IS NOT NULL
    """

    params = {"tenant_id": tenant_id}

    if company_id is not None:
        query += " AND company_id = :company_id"
        params["company_id"] = company_id

    query += """
        GROUP BY DATE_TRUNC('month', date_order)
        ORDER BY month DESC
        LIMIT 2
    )
    SELECT *
    FROM monthly_sales
    ORDER BY month DESC
    """

    rows = run_query(query, params)

    if len(rows) < 2:
        return {
            "tool_name": "analyze_variance_tool",
            "tenant_id": tenant_id,
            "company_id": company_id,
            "status": "not_enough_data",
            "message": "Not enough monthly sales data to compare current month vs previous month.",
            "periods": rows,
            "note": "Real data from PostgreSQL fact_sales_orders.",
        }

    current = rows[0]
    previous = rows[1]

    current_revenue = float(current.get("revenue") or 0)
    previous_revenue = float(previous.get("revenue") or 0)

    current_orders = int(current.get("order_count") or 0)
    previous_orders = int(previous.get("order_count") or 0)

    current_aov = float(current.get("average_order_value") or 0)
    previous_aov = float(previous.get("average_order_value") or 0)

    def safe_pct_change(current_value: float, previous_value: float) -> float:
        if previous_value == 0:
            return 0.0
        return ((current_value - previous_value) / previous_value) * 100

    revenue_change = current_revenue - previous_revenue
    revenue_change_pct = safe_pct_change(current_revenue, previous_revenue)

    order_change = current_orders - previous_orders
    order_change_pct = safe_pct_change(current_orders, previous_orders)

    aov_change = current_aov - previous_aov
    aov_change_pct = safe_pct_change(current_aov, previous_aov)

    if revenue_change > 0:
        direction = "Increase"
    elif revenue_change < 0:
        direction = "Decrease"
    else:
        direction = "Flat"

    return {
        "tool_name": "analyze_variance_tool",
        "tenant_id": tenant_id,
        "company_id": company_id,
        "currency": "unknown",
        "comparison": {
            "current_month": str(current.get("month")),
            "previous_month": str(previous.get("month")),
        },
        "current_period": {
            "revenue": current_revenue,
            "order_count": current_orders,
            "average_order_value": current_aov,
        },
        "previous_period": {
            "revenue": previous_revenue,
            "order_count": previous_orders,
            "average_order_value": previous_aov,
        },
        "variance": {
            "revenue_change": revenue_change,
            "revenue_change_pct": revenue_change_pct,
            "order_change": order_change,
            "order_change_pct": order_change_pct,
            "average_order_value_change": aov_change,
            "average_order_value_change_pct": aov_change_pct,
            "direction": direction,
        },
        "note": "Real data from PostgreSQL fact_sales_orders. Only confirmed sales states are included: sale, done.",
    }








def get_time_series_data_tool(
    tenant_id: str,
    company_id: int | None = None,
    granularity: str = "month",
) -> dict:
    """
    Real revenue trend from PostgreSQL fact_sales_orders.

    Uses confirmed sales only:
    state IN ('sale', 'done')
    """

    allowed_granularities = ["day", "week", "month"]

    if granularity not in allowed_granularities:
        granularity = "month"

    query = f"""
    SELECT
        DATE_TRUNC('{granularity}', date_order) AS period,
        COALESCE(SUM(amount_total), 0) AS revenue,
        COUNT(*) AS order_count,
        COALESCE(AVG(amount_total), 0) AS average_order_value
    FROM fact_sales_orders
    WHERE tenant_id = :tenant_id
      AND state IN ('sale', 'done')
      AND date_order IS NOT NULL
    """

    params = {
        "tenant_id": tenant_id,
    }

    if company_id is not None:
        query += " AND company_id = :company_id"
        params["company_id"] = company_id

    query += """
    GROUP BY period
    ORDER BY period ASC
    """

    rows = run_query(query, params)

    points = []

    for row in rows:
        points.append(
            {
                "period": str(row.get("period")),
                "revenue": float(row.get("revenue") or 0),
                "order_count": int(row.get("order_count") or 0),
                "average_order_value": float(row.get("average_order_value") or 0),
            }
        )

    return {
        "tool_name": "get_time_series_data_tool",
        "tenant_id": tenant_id,
        "company_id": company_id,
        "granularity": granularity,
        "currency": "unknown",
        "points": points,
        "note": "Real data from PostgreSQL fact_sales_orders. Only confirmed sales states are included: sale, done.",
    }



def forecast_sales_tool(
    tenant_id: str,
    company_id: int | None = None,
    forecast_periods: int = 3,
) -> dict:
    """
    Real sales forecast from PostgreSQL fact_sales_orders.

    Method:
    - Monthly revenue history from confirmed sales orders.
    - Simple Moving Average forecast using the last 3 months.
    - This is the first implementation. Later it can be replaced by Prophet.
    """

    from datetime import datetime
    from dateutil.relativedelta import relativedelta

    history_query = """
    SELECT
        DATE_TRUNC('month', date_order) AS month,
        COALESCE(SUM(amount_total), 0) AS revenue,
        COUNT(*) AS order_count
    FROM fact_sales_orders
    WHERE tenant_id = :tenant_id
      AND state IN ('sale', 'done')
      AND date_order IS NOT NULL
    """

    params = {
        "tenant_id": tenant_id,
    }

    if company_id is not None:
        history_query += " AND company_id = :company_id"
        params["company_id"] = company_id

    history_query += """
    GROUP BY DATE_TRUNC('month', date_order)
    ORDER BY month ASC
    """

    rows = run_query(history_query, params)

    history = []

    for row in rows:
        month_value = row.get("month")

        history.append(
            {
                "month": str(month_value),
                "revenue": float(row.get("revenue") or 0),
                "order_count": int(row.get("order_count") or 0),
            }
        )

    if len(history) < 3:
        return {
            "tool_name": "forecast_sales_tool",
            "tenant_id": tenant_id,
            "company_id": company_id,
            "status": "not_enough_data",
            "message": "At least 3 months of sales data are needed for a simple moving-average forecast.",
            "history": history,
            "forecast": [],
            "note": "Real data from PostgreSQL fact_sales_orders. Forecast method: simple moving average.",
        }

    last_3_months = history[-3:]

    avg_revenue = sum(item["revenue"] for item in last_3_months) / 3
    avg_order_count = sum(item["order_count"] for item in last_3_months) / 3

    # Get the last month directly from the last history point
    last_month_str = history[-1]["month"]

    try:
        last_month_dt = datetime.fromisoformat(last_month_str)
    except ValueError:
        last_month_dt = datetime.strptime(last_month_str[:10], "%Y-%m-%d")

    forecast = []

    for i in range(1, forecast_periods + 1):
        forecast_month = last_month_dt + relativedelta(months=i)

        forecast.append(
            {
                "month": forecast_month.strftime("%Y-%m-01"),
                "forecast_revenue": avg_revenue,
                "forecast_order_count": round(avg_order_count),
                "method": "3-month simple moving average",
            }
        )

    latest_revenue = history[-1]["revenue"]
    trend_vs_forecast = avg_revenue - latest_revenue

    if trend_vs_forecast > 0:
        forecast_direction = "Expected increase versus latest month"
    elif trend_vs_forecast < 0:
        forecast_direction = "Expected decrease versus latest month"
    else:
        forecast_direction = "Expected flat versus latest month"

    return {
        "tool_name": "forecast_sales_tool",
        "tenant_id": tenant_id,
        "company_id": company_id,
        "currency": "unknown",
        "method": "3-month simple moving average",
        "history_months_used": last_3_months,
        "latest_month": history[-1],
        "forecast_periods": forecast_periods,
        "forecast": forecast,
        "forecast_direction": forecast_direction,
        "note": "Real data from PostgreSQL fact_sales_orders. Only confirmed sales states are included: sale, done.",
    }


def analyze_profitability_tool(
    tenant_id: str,
    company_id: int | None = None,
    limit: int = 10,
) -> dict:
    """
    Real profitability analysis from PostgreSQL.

    Uses:
    - fact_sales_order_lines for revenue and quantity sold
    - dim_products for standard_price/product cost and category

    Formula:
    estimated_cost = quantity_sold * standard_price
    gross_profit = revenue - estimated_cost
    gross_margin_pct = gross_profit / revenue * 100
    """

    summary_query = """
    SELECT
        COALESCE(SUM(l.price_total), 0) AS total_revenue,
        COALESCE(SUM(l.product_uom_qty * COALESCE(p.standard_price, 0)), 0) AS estimated_cost,
        COALESCE(SUM(l.price_total) - SUM(l.product_uom_qty * COALESCE(p.standard_price, 0)), 0) AS gross_profit
    FROM fact_sales_order_lines l
    LEFT JOIN dim_products p
        ON p.tenant_id = l.tenant_id
       AND p.odoo_id = l.product_id
    WHERE l.tenant_id = :tenant_id
      AND l.state IN ('sale', 'done')
      AND l.product_id IS NOT NULL
    """

    product_query = """
    SELECT
        l.product_id,
        l.product_name,
        COALESCE(p.category_name, 'Uncategorized') AS category_name,
        COALESCE(SUM(l.product_uom_qty), 0) AS quantity_sold,
        COALESCE(SUM(l.price_total), 0) AS revenue,
        COALESCE(SUM(l.product_uom_qty * COALESCE(p.standard_price, 0)), 0) AS estimated_cost,
        COALESCE(SUM(l.price_total) - SUM(l.product_uom_qty * COALESCE(p.standard_price, 0)), 0) AS gross_profit
    FROM fact_sales_order_lines l
    LEFT JOIN dim_products p
        ON p.tenant_id = l.tenant_id
       AND p.odoo_id = l.product_id
    WHERE l.tenant_id = :tenant_id
      AND l.state IN ('sale', 'done')
      AND l.product_id IS NOT NULL
    """

    category_query = """
    SELECT
        COALESCE(p.category_name, 'Uncategorized') AS category_name,
        COALESCE(SUM(l.product_uom_qty), 0) AS quantity_sold,
        COALESCE(SUM(l.price_total), 0) AS revenue,
        COALESCE(SUM(l.product_uom_qty * COALESCE(p.standard_price, 0)), 0) AS estimated_cost,
        COALESCE(SUM(l.price_total) - SUM(l.product_uom_qty * COALESCE(p.standard_price, 0)), 0) AS gross_profit
    FROM fact_sales_order_lines l
    LEFT JOIN dim_products p
        ON p.tenant_id = l.tenant_id
       AND p.odoo_id = l.product_id
    WHERE l.tenant_id = :tenant_id
      AND l.state IN ('sale', 'done')
      AND l.product_id IS NOT NULL
    """

    params = {
        "tenant_id": tenant_id,
        "limit": limit,
    }

    if company_id is not None:
        summary_query += " AND l.company_id = :company_id"
        product_query += " AND l.company_id = :company_id"
        category_query += " AND l.company_id = :company_id"
        params["company_id"] = company_id

    product_query += """
    GROUP BY
        l.product_id,
        l.product_name,
        p.category_name
    ORDER BY gross_profit DESC
    LIMIT :limit
    """

    category_query += """
    GROUP BY
        p.category_name
    ORDER BY gross_profit DESC
    LIMIT :limit
    """

    summary_rows = run_query(summary_query, params)
    product_rows = run_query(product_query, params)
    category_rows = run_query(category_query, params)

    summary = summary_rows[0] if summary_rows else {}

    total_revenue = float(summary.get("total_revenue") or 0)
    estimated_cost = float(summary.get("estimated_cost") or 0)
    gross_profit = float(summary.get("gross_profit") or 0)

    gross_margin_ratio = calculate_ratio(gross_profit, total_revenue)
    gross_margin_pct = gross_margin_ratio * 100

    top_products = []

    for row in product_rows:
        revenue = float(row.get("revenue") or 0)
        product_gross_profit = float(row.get("gross_profit") or 0)

        top_products.append(
            {
                "product_id": row.get("product_id"),
                "product": row.get("product_name"),
                "category": row.get("category_name"),
                "quantity_sold": float(row.get("quantity_sold") or 0),
                "revenue": revenue,
                "estimated_cost": float(row.get("estimated_cost") or 0),
                "gross_profit": product_gross_profit,
                "gross_margin_pct": calculate_ratio(product_gross_profit, revenue) * 100,
            }
        )

    category_breakdown = []

    for row in category_rows:
        revenue = float(row.get("revenue") or 0)
        category_gross_profit = float(row.get("gross_profit") or 0)

        category_breakdown.append(
            {
                "category": row.get("category_name"),
                "quantity_sold": float(row.get("quantity_sold") or 0),
                "revenue": revenue,
                "estimated_cost": float(row.get("estimated_cost") or 0),
                "gross_profit": category_gross_profit,
                "gross_margin_pct": calculate_ratio(category_gross_profit, revenue) * 100,
            }
        )

    if gross_margin_pct >= 30:
        profitability_status = "Strong"
    elif gross_margin_pct >= 15:
        profitability_status = "Stable"
    elif gross_margin_pct > 0:
        profitability_status = "Weak"
    else:
        profitability_status = "Loss"

    return {
        "tool_name": "analyze_profitability_tool",
        "tenant_id": tenant_id,
        "company_id": company_id,
        "currency": "unknown",
        "total_revenue": total_revenue,
        "estimated_cost": estimated_cost,
        "gross_profit": gross_profit,
        "gross_margin_pct": gross_margin_pct,
        "profitability_status": profitability_status,
        "top_profitable_products": top_products,
        "category_breakdown": category_breakdown,
        "note": (
            "Real data from PostgreSQL. Revenue uses fact_sales_order_lines. "
            "Estimated cost uses dim_products.standard_price. This is an estimated gross margin, not final accounting margin."
        ),
    }










def get_customer_metrics_tool(
    tenant_id: str,
    company_id: int | None = None,
    company_ids: list[int] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 10,
) -> dict:
    """
    Real top customer metrics from PostgreSQL.
    Supports selected companies and optional date range.
    """

    selected_company_ids = normalize_company_ids(
        company_id=company_id,
        companies=company_ids,
    )

    sales_query = """
    SELECT
        partner_id,
        partner_name,
        COUNT(*) AS order_count,
        COALESCE(SUM(amount_total), 0) AS total_revenue,
        COALESCE(AVG(amount_total), 0) AS average_order_value,
        MIN(date_order) AS first_order_date,
        MAX(date_order) AS last_order_date
    FROM fact_sales_orders
    WHERE tenant_id = :tenant_id
      AND state IN ('sale', 'done')
      AND partner_id IS NOT NULL
    """

    params = {
        "tenant_id": tenant_id,
        "limit": limit,
    }

    if selected_company_ids:
        placeholders = []
        for index, cid in enumerate(selected_company_ids):
            key = f"company_{index}"
            placeholders.append(f":{key}")
            params[key] = cid
        sales_query += f" AND company_id IN ({', '.join(placeholders)})"

    if start_date:
        sales_query += " AND date_order >= :start_date"
        params["start_date"] = start_date

    if end_date:
        sales_query += " AND date_order < (CAST(:end_date AS date) + INTERVAL '1 day')"
        params["end_date"] = end_date

    sales_query += """
    GROUP BY partner_id, partner_name
    ORDER BY total_revenue DESC
    LIMIT :limit
    """

    overdue_query = """
    SELECT
        partner_id,
        COALESCE(SUM(amount_residual), 0) AS overdue_amount,
        COUNT(*) AS overdue_invoice_count,
        MAX(CURRENT_DATE - invoice_date_due) AS max_days_overdue
    FROM fact_account_moves
    WHERE tenant_id = :tenant_id
      AND move_type = 'out_invoice'
      AND state = 'posted'
      AND payment_state IN ('not_paid', 'partial')
      AND amount_residual > 0
      AND invoice_date_due IS NOT NULL
      AND invoice_date_due < CURRENT_DATE
    """

    overdue_params = {"tenant_id": tenant_id}

    if selected_company_ids:
        placeholders = []
        for index, cid in enumerate(selected_company_ids):
            key = f"overdue_company_{index}"
            placeholders.append(f":{key}")
            overdue_params[key] = cid
        overdue_query += f" AND company_id IN ({', '.join(placeholders)})"

    overdue_query += """
    GROUP BY partner_id
    """

    sales_rows = run_query(sales_query, params)
    overdue_rows = run_query(overdue_query, overdue_params)

    overdue_by_partner = {
        row.get("partner_id"): {
            "overdue_amount": float(row.get("overdue_amount") or 0),
            "overdue_invoice_count": int(row.get("overdue_invoice_count") or 0),
            "max_days_overdue": int(row.get("max_days_overdue") or 0),
        }
        for row in overdue_rows
    }

    customers = []

    for row in sales_rows:
        partner_id = row.get("partner_id")
        overdue = overdue_by_partner.get(
            partner_id,
            {
                "overdue_amount": 0.0,
                "overdue_invoice_count": 0,
                "max_days_overdue": 0,
            },
        )

        overdue_amount = overdue["overdue_amount"]
        total_revenue = float(row.get("total_revenue") or 0)
        overdue_to_revenue_ratio = calculate_ratio(overdue_amount, total_revenue)

        if overdue_to_revenue_ratio >= 0.5 or overdue["max_days_overdue"] >= 90:
            risk_level = "High"
        elif overdue_to_revenue_ratio >= 0.2 or overdue["max_days_overdue"] >= 60:
            risk_level = "Medium"
        else:
            risk_level = "Low"

        customers.append(
            {
                "partner_id": partner_id,
                "customer": row.get("partner_name"),
                "order_count": int(row.get("order_count") or 0),
                "total_revenue": total_revenue,
                "average_order_value": float(row.get("average_order_value") or 0),
                "first_order_date": str(row.get("first_order_date")) if row.get("first_order_date") else None,
                "last_order_date": str(row.get("last_order_date")) if row.get("last_order_date") else None,
                "overdue_amount": overdue_amount,
                "overdue_invoice_count": overdue["overdue_invoice_count"],
                "max_days_overdue": overdue["max_days_overdue"],
                "risk_level": risk_level,
            }
        )

    high_risk_count = sum(1 for c in customers if c["risk_level"] == "High")

    return {
        "tool_name": "get_customer_metrics_tool",
        "tenant_id": tenant_id,
        "company_id": company_id,
        "company_ids": selected_company_ids,
        "start_date": start_date,
        "end_date": end_date,
        "limit": limit,
        "currency": "unknown",
        "top_customers": customers,
        "high_risk_customer_count": high_risk_count,
        "note": "Real data from PostgreSQL fact_sales_orders and fact_account_moves.",
    }

def analyze_variance_tool(
    tenant_id: str,
    company_id: int | None = None,
) -> dict:
    """
    Real period-over-period sales variance from PostgreSQL fact_sales_orders.

    Compares:
    - Current month
    - Previous month

    Uses confirmed sales only:
    state IN ('sale', 'done')
    """

    query = """
    WITH monthly_sales AS (
        SELECT
            DATE_TRUNC('month', date_order) AS month,
            COALESCE(SUM(amount_total), 0) AS revenue,
            COUNT(*) AS order_count,
            COALESCE(AVG(amount_total), 0) AS average_order_value
        FROM fact_sales_orders
        WHERE tenant_id = :tenant_id
          AND state IN ('sale', 'done')
          AND date_order IS NOT NULL
    """

    params = {"tenant_id": tenant_id}

    if company_id is not None:
        query += " AND company_id = :company_id"
        params["company_id"] = company_id

    query += """
        GROUP BY DATE_TRUNC('month', date_order)
        ORDER BY month DESC
        LIMIT 2
    )
    SELECT *
    FROM monthly_sales
    ORDER BY month DESC
    """

    rows = run_query(query, params)

    if len(rows) < 2:
        return {
            "tool_name": "analyze_variance_tool",
            "tenant_id": tenant_id,
            "company_id": company_id,
            "status": "not_enough_data",
            "message": "Not enough monthly sales data to compare current month vs previous month.",
            "periods": rows,
            "note": "Real data from PostgreSQL fact_sales_orders.",
        }

    current = rows[0]
    previous = rows[1]

    current_revenue = float(current.get("revenue") or 0)
    previous_revenue = float(previous.get("revenue") or 0)

    current_orders = int(current.get("order_count") or 0)
    previous_orders = int(previous.get("order_count") or 0)

    current_aov = float(current.get("average_order_value") or 0)
    previous_aov = float(previous.get("average_order_value") or 0)

    revenue_change = current_revenue - previous_revenue
    revenue_change_pct = calculate_ratio(revenue_change, previous_revenue) * 100

    order_change = current_orders - previous_orders
    order_change_pct = calculate_ratio(order_change, previous_orders) * 100

    aov_change = current_aov - previous_aov
    aov_change_pct = calculate_ratio(aov_change, previous_aov) * 100

    if revenue_change > 0:
        direction = "Increase"
    elif revenue_change < 0:
        direction = "Decrease"
    else:
        direction = "Flat"

    return {
        "tool_name": "analyze_variance_tool",
        "tenant_id": tenant_id,
        "company_id": company_id,
        "currency": "unknown",
        "comparison": {
            "current_month": str(current.get("month")),
            "previous_month": str(previous.get("month")),
        },
        "current_period": {
            "revenue": current_revenue,
            "order_count": current_orders,
            "average_order_value": current_aov,
        },
        "previous_period": {
            "revenue": previous_revenue,
            "order_count": previous_orders,
            "average_order_value": previous_aov,
        },
        "variance": {
            "revenue_change": revenue_change,
            "revenue_change_pct": revenue_change_pct,
            "order_change": order_change,
            "order_change_pct": order_change_pct,
            "average_order_value_change": aov_change,
            "average_order_value_change_pct": aov_change_pct,
            "direction": direction,
        },
        "note": "Real data from PostgreSQL fact_sales_orders. Only confirmed sales states are included: sale, done.",
    }



# ─────────────────────────────
# FAST TOOL SELECTION
# ─────────────────────────────
def select_fast_tool(message: str) -> str | None:
    """
    Deterministic tool selector for FAST path.
    Order matters: more specific tools must come before general tools.
    """

    text = normalize_business_text_for_intent(message)

    # Flexible sales summary phrasing
    if any(phrase in text for phrase in [
        "how much did we sell",
        "how much we sold",
        "what did we sell",
        "sales summary",
        "total sales",
        "sales total",
        "sold in",
        "sell in",
    ]):
        return "get_sales_summary_tool"

        # 0. Graph / chart requests
    if any(word in text for word in [
        "graph",
        "chart",
        "plot",
        "visualize",
        "visualization",
        "draw",
        "sales graph",
        "sales chart",
        "revenue graph",
        "revenue chart",
        "plot sales",
        "plot revenue",
        "make graph",
        "make a graph",
        "make for me a graph",
        "show graph",
        "show chart",
    ]) and any(word in text for word in [
        "sales",
        "revenue",
        "orders",
        "order",
    ]):
        return "get_sales_chart_data_tool"



    




    # 1. Variance / comparison
    if any(word in text for word in [
        "variance",
        "compare sales",
        "compare revenue",
        "month over month",
        "period over period",
        "revenue change",
        "sales change",
        "sales month over month",
    ]):
        return "analyze_variance_tool"

    # 2. Sales trend / time series
    if any(word in text for word in [
        "sales trend",
        "revenue trend",
        "time series",
        "monthly sales",
        "daily sales",
        "weekly sales",
        "sales over time",
        "revenue over time",
        "monthly revenue",
        "revenue by month",
        "sales by month",
    ]):
        return "get_time_series_data_tool"


    if any(word in text for word in [
        "generate report",
        "pdf report",
        "business report",
        "financial report",
        "create report",
        "download report",
        "report pdf",
    ]):
        return "generate_report_tool"





    if any(word in text for word in [
        "business health",
        "business health score",
        "company health",
        "overall health",
        "health score",
        "how healthy is the business",
        "business status",
    ]):
        return "get_business_health_score_tool"



    if any(word in text for word in [
        "profitability",
        "profit analysis",
        "profit margin",
        "gross margin",
        "gross profit",
        "most profitable products",
        "profitable products",
        "category profitability",
        "margin analysis",
    ]):
        return "analyze_profitability_tool"




    # 3. Receivables analysis
    if any(word in text for word in [
        "receivables analysis",
        "overdue receivables",
        "overdue invoices",
        "top overdue customers",
        "who owes",
        "customers owe",
        "ar aging",
        "accounts receivable aging",
    ]):
        return "get_receivables_analysis_tool"


    if any(word in text for word in [
        "forecast sales",
        "sales forecast",
        "forecast revenue",
        "revenue forecast",
        "predict sales",
        "predict revenue",
        "next month sales",
        "next months sales",
        "future sales",
        "future revenue",
    ]):
        return "forecast_sales_tool"

    if any(word in text for word in [
        "send email",
        "email report",
        "email this",
        "prepare email",
        "draft email",
        "send this by email",
        "email the report",
    ]):
        return "send_email_tool"



    # 4. Sales summary
    if any(word in text for word in [
        "sales summary",
        "revenue summary",
        "total sales",
        "sales total",
    ]):
        return "get_sales_summary_tool"

    # 5. Top products
    if any(phrase in text for phrase in [
        "top products",
        "best products",
        "top selling",
        "best selling",
        "best-selling",
        "top 5 products",
        "top 10 products",
        "products by revenue",
        "highest revenue products",
        "which products generated",
        "most sold products",
        "most selling products",
    ]):
        return "get_top_products_tool"





    if any(phrase in text for phrase in [
        "inventory efficiency",
        "inventory turnover",
        "turnover ratio",
        "days inventory",
        "days inventory on hand",
        "stock efficiency",
        "stock performance",
        "inventory performance",
        "inventory value",
        "stock value",
        "movement summary",
        "stock movement summary",
        "inventory movement summary",
        "how efficient is inventory",
        "how efficient is our inventory",
    ]):
        return "get_inventory_efficiency_tool"



    # 6. Inventory alerts
    if any(phrase in text for phrase in [
        "low stock",
        "inventory alert",
        "inventory alerts",
        "inventory problems",
        "stock problems",
        "stock issue",
        "stock issues",
        "stock alert",
        "stock alerts",
        "available stock",
        "available quantity",
        "expiring",
        "expiring lots",
        "expiry",
        "near expiry",
        "out of stock",
        "shortage",
        "shortages",
        "any low stock",
        "which products are low stock",
    ]):
        return "get_inventory_alerts_tool"


    if any(phrase in text for phrase in [
        "customer metrics",
        "top customers",
        "top clients",
        "best customers",
        "best clients",
        "customer ranking",
        "client ranking",
        "customer revenue",
        "customers by revenue",
        "clients by revenue",
        "which customers generate",
        "which clients generate",
        "who are the best customers",
        "who are the top customers",
        "customer risk",
        "high risk customers",
        "customer overdue risk",
    ]):
        return "get_customer_metrics_tool"





    # 7. Cash flow health
    if any(word in text for word in [
        "cash flow",
        "cash flow health",
        "liquidity",
        "accounts receivable",
        "accounts payable",
        "payables",
    ]):
        return "get_cash_flow_health_tool"

    # 8. Ratio calculator
    if any(word in text for word in [
        "ratio",
        "calculate ratio",
    ]):
        return "calculate_ratio_tool"
    

    if any(word in text for word in [
        "send alert",
        "create alert",
        "notify dashboard",
        "dashboard alert",
        "make an alert",
        "alert me",
    ]):
        return "send_alert_tool"





    if any(word in text for word in [
        "database question",
        "custom database",
        "sales by company",
        "revenue by company",
        "orders by state",
        "order status",
        "revenue by month",
        "overdue by company",
        "who owes the most",
        "inventory value by company",
        "stock value by company",
    ]):
        return "ask_database_custom_question"

    return None

def run_fast_tool(
    message: str,
    tenant_id: str,
    company_id: int | None = None,
    companies: list[int] | None = None,
    context: str | None = None,
) -> dict | None:
    company_ids = companies or ([company_id] if company_id is not None else None)
    start_date, end_date, period_label = extract_date_range(message)
    tool_name = select_fast_tool(message)

    if tool_name is None:
        return None
    

    if tool_name == "get_sales_chart_data_tool":
        return get_sales_chart_data_tool(
            tenant_id=tenant_id,
            company_id=company_id,
            granularity="month",
        )

    if tool_name == "get_sales_summary_tool":
        return get_sales_summary_tool(
            tenant_id=tenant_id,
            company_id=company_id,
            company_ids=company_ids,
            start_date=start_date,
            end_date=end_date,
            period=period_label or "selected_period",
        )

    if tool_name == "get_top_products_tool":
        return get_top_products_tool(
            tenant_id=tenant_id,
            company_id=company_id,
            company_ids=company_ids,
            start_date=start_date,
            end_date=end_date,
            limit=10,
        )

    if tool_name == "get_inventory_alerts_tool":
        return get_inventory_alerts_tool(
            tenant_id=tenant_id,
            company_id=company_id,
            company_ids=company_ids,
        )

    if tool_name == "get_cash_flow_health_tool":
        return get_cash_flow_health_tool(
            tenant_id=tenant_id,
            company_id=company_id,
        )
    
    if tool_name == "get_receivables_analysis_tool":
        return get_receivables_analysis_tool(
            tenant_id=tenant_id,
            company_id=company_id,
        )

    if tool_name == "get_time_series_data_tool":
        return get_time_series_data_tool(
            tenant_id=tenant_id,
            company_id=company_id,
            granularity="month",
        )

    if tool_name == "analyze_variance_tool":
        return analyze_variance_tool(
            tenant_id=tenant_id,
            company_id=company_id,
        )

    if tool_name == "get_time_series_data_tool":
        return get_time_series_data_tool(
            tenant_id=tenant_id,
            company_id=company_id,
            granularity="month",
        )

    if tool_name == "analyze_variance_tool":
        return analyze_variance_tool(
            tenant_id=tenant_id,
            company_id=company_id,
        )
    


    if tool_name == "forecast_sales_tool":
        return forecast_sales_tool(
            tenant_id=tenant_id,
            company_id=company_id,
            forecast_periods=3,
        )

    if tool_name == "generate_report_tool":
        return generate_report_tool(
            tenant_id=tenant_id,
            company_id=company_id,
        )


    if tool_name == "get_customer_metrics_tool":
        return get_customer_metrics_tool(
            tenant_id=tenant_id,
            company_id=company_id,
            company_ids=company_ids,
            start_date=start_date,
            end_date=end_date,
            limit=10,
        )

    if tool_name == "get_inventory_efficiency_tool":
        return get_inventory_efficiency_tool(
            tenant_id=tenant_id,
            company_id=company_id,
            company_ids=company_ids,
        )

    if tool_name == "get_business_health_score_tool":
        return get_business_health_score_tool(
            tenant_id=tenant_id,
            company_id=company_id,
        )


    if tool_name == "analyze_profitability_tool":
        return analyze_profitability_tool(
            tenant_id=tenant_id,
            company_id=company_id,
        )

    if tool_name == "ask_database_custom_question":
        return ask_database_custom_question(
            tenant_id=tenant_id,
            company_id=company_id,
            question=message,
        )


    if tool_name == "generate_report_tool":
        return generate_report_tool(
            tenant_id=tenant_id,
            company_id=company_id,
            report_type="business_summary",
        )


    if tool_name == "send_alert_tool":
        return send_alert_tool(
            tenant_id=tenant_id,
            company_id=company_id,
            title="AI Financial Advisor Alert",
            message=message,
            severity="info",
            source_tool="chatbot",
        )
    if tool_name == "send_email_tool":
        return send_email_tool(
            tenant_id=tenant_id,
            company_id=company_id,
            to_email="test@example.com",
            subject="AI Financial Advisor Update",
            body=message,
            source_tool="chatbot",
        )

    # For now, ratio tool needs explicit numeric arguments.
    # So we do not auto-run it from text yet.
    return None




# ─────────────────────────────
# REASONING TOOL SELECTION
# ─────────────────────────────
def select_reasoning_tools(message: str, plan: dict | None = None) -> list[str]:
    """
    Select multiple tools for REASONING path.
    Unlike FAST path, reasoning can use more than one tool.
    """

    text = message.lower()

    selected_tools = []

    # Sales / revenue / margin questions
    if any(word in text for word in ["sales", "revenue", "margin", "profit", "profitability", "performance"]):
        selected_tools.append("get_sales_summary_tool")
        selected_tools.append("get_top_products_tool")

    # Inventory / stock questions
    if any(word in text for word in ["inventory", "stock", "low stock", "expiring", "warehouse"]):
        selected_tools.append("get_inventory_alerts_tool")

    # Cash flow / AR / AP questions
    if any(word in text for word in ["cash flow", "liquidity", "receivables", "payables", "ar", "ap"]):
        selected_tools.append("get_cash_flow_health_tool")

    # If the plan mentions tools/data sources, use that too
    if plan:
        plan_text = str(plan).lower()

        if any(word in plan_text for word in ["sales", "revenue", "margin", "profit"]):
            if "get_sales_summary_tool" not in selected_tools:
                selected_tools.append("get_sales_summary_tool")

        if any(word in plan_text for word in ["product", "product mix", "top products"]):
            if "get_top_products_tool" not in selected_tools:
                selected_tools.append("get_top_products_tool")

        if any(word in plan_text for word in ["inventory", "stock", "expiring"]):
            if "get_inventory_alerts_tool" not in selected_tools:
                selected_tools.append("get_inventory_alerts_tool")

        if any(word in plan_text for word in ["cash", "liquidity", "receivable", "payable"]):
            if "get_cash_flow_health_tool" not in selected_tools:
                selected_tools.append("get_cash_flow_health_tool")

    # Safe fallback for reasoning questions
    if not selected_tools:
        selected_tools.append("get_sales_summary_tool")
        selected_tools.append("get_cash_flow_health_tool")

    # Remove duplicates while preserving order
    unique_tools = []
    for tool in selected_tools:
        if tool not in unique_tools:
            unique_tools.append(tool)

    return unique_tools


def run_reasoning_tools(
    message: str,
    tenant_id: str,
    company_id: int | None = None,
    plan: dict | None = None,
) -> dict:
    """
    Runs multiple tools for the REASONING path.
    """

    selected_tools = select_reasoning_tools(message, plan)

    results = {
        "selected_tools": selected_tools,
        "tool_results": {}
    }

    for tool_name in selected_tools:
        if tool_name == "get_sales_summary_tool":
            results["tool_results"][tool_name] = get_sales_summary_tool(
                tenant_id=tenant_id,
                company_id=company_id,
            )

        elif tool_name == "get_top_products_tool":
            results["tool_results"][tool_name] = get_top_products_tool(
                tenant_id=tenant_id,
                company_id=company_id,
            )

        elif tool_name == "get_inventory_alerts_tool":
            results["tool_results"][tool_name] = get_inventory_alerts_tool(
                tenant_id=tenant_id,
                company_id=company_id,
            )

        elif tool_name == "get_cash_flow_health_tool":
            results["tool_results"][tool_name] = get_cash_flow_health_tool(
                tenant_id=tenant_id,
                company_id=company_id,
            )

    return results




def ask_database_custom_question(
    tenant_id: str,
    question: str,
    company_id: int | None = None,
) -> dict:
    """
    Safe custom database question tool.

    This first version does NOT generate arbitrary SQL using Claude.
    It maps common business questions to safe predefined SQL queries.

    Uses real PostgreSQL data synced from Odoo.
    """

    text = question.lower()

    # ─────────────────────────────
    # Safety: only predefined questions
    # ─────────────────────────────
    params = {"tenant_id": tenant_id}

    # 1. Sales by company
    if any(word in text for word in [
        "sales by company",
        "revenue by company",
        "total revenue by company",
        "which company has highest sales",
    ]):
        query = """
        SELECT
            company_id,
            company_name,
            COALESCE(SUM(amount_total), 0) AS total_revenue,
            COUNT(*) AS order_count
        FROM fact_sales_orders
        WHERE tenant_id = :tenant_id
          AND state IN ('sale', 'done')
        """

        if company_id is not None:
            query += " AND company_id = :company_id"
            params["company_id"] = company_id

        query += """
        GROUP BY company_id, company_name
        ORDER BY total_revenue DESC
        """

        rows = run_query(query, params)

        return {
            "tool_name": "ask_database_custom_question",
            "tenant_id": tenant_id,
            "company_id": company_id,
            "question": question,
            "query_type": "sales_by_company",
            "results": [
                {
                    "company_id": row.get("company_id"),
                    "company": row.get("company_name"),
                    "total_revenue": float(row.get("total_revenue") or 0),
                    "order_count": int(row.get("order_count") or 0),
                }
                for row in rows
            ],
            "note": "Real data from PostgreSQL fact_sales_orders.",
        }

    # 2. Orders count by state
    if any(word in text for word in [
        "orders by state",
        "sales orders by state",
        "order status",
        "sales status",
    ]):
        query = """
        SELECT
            state,
            COUNT(*) AS order_count,
            COALESCE(SUM(amount_total), 0) AS total_amount
        FROM fact_sales_orders
        WHERE tenant_id = :tenant_id
        """

        if company_id is not None:
            query += " AND company_id = :company_id"
            params["company_id"] = company_id

        query += """
        GROUP BY state
        ORDER BY order_count DESC
        """

        rows = run_query(query, params)

        return {
            "tool_name": "ask_database_custom_question",
            "tenant_id": tenant_id,
            "company_id": company_id,
            "question": question,
            "query_type": "orders_by_state",
            "results": [
                {
                    "state": row.get("state"),
                    "order_count": int(row.get("order_count") or 0),
                    "total_amount": float(row.get("total_amount") or 0),
                }
                for row in rows
            ],
            "note": "Real data from PostgreSQL fact_sales_orders.",
        }

    # 3. Revenue by month
    if any(word in text for word in [
        "revenue by month",
        "sales by month",
        "monthly revenue",
        "monthly sales",
    ]):
        query = """
        SELECT
            DATE_TRUNC('month', date_order) AS month,
            COALESCE(SUM(amount_total), 0) AS revenue,
            COUNT(*) AS order_count
        FROM fact_sales_orders
        WHERE tenant_id = :tenant_id
          AND state IN ('sale', 'done')
          AND date_order IS NOT NULL
        """

        if company_id is not None:
            query += " AND company_id = :company_id"
            params["company_id"] = company_id

        query += """
        GROUP BY DATE_TRUNC('month', date_order)
        ORDER BY month ASC
        """

        rows = run_query(query, params)

        return {
            "tool_name": "ask_database_custom_question",
            "tenant_id": tenant_id,
            "company_id": company_id,
            "question": question,
            "query_type": "revenue_by_month",
            "results": [
                {
                    "month": str(row.get("month")),
                    "revenue": float(row.get("revenue") or 0),
                    "order_count": int(row.get("order_count") or 0),
                }
                for row in rows
            ],
            "note": "Real data from PostgreSQL fact_sales_orders.",
        }

    # 4. Overdue customers
    if any(word in text for word in [
        "overdue by company",
        "overdue customers",
        "highest overdue",
        "customers with overdue",
        "who owes the most",
    ]):
        query = """
        SELECT
            partner_id,
            partner_name,
            company_id,
            company_name,
            COALESCE(SUM(amount_residual), 0) AS overdue_amount,
            COUNT(*) AS overdue_invoice_count,
            MAX(CURRENT_DATE - invoice_date_due) AS max_days_overdue
        FROM fact_account_moves
        WHERE tenant_id = :tenant_id
          AND move_type = 'out_invoice'
          AND state = 'posted'
          AND payment_state IN ('not_paid', 'partial')
          AND amount_residual > 0
          AND invoice_date_due IS NOT NULL
          AND invoice_date_due < CURRENT_DATE
        """

        if company_id is not None:
            query += " AND company_id = :company_id"
            params["company_id"] = company_id

        query += """
        GROUP BY partner_id, partner_name, company_id, company_name
        ORDER BY overdue_amount DESC
        LIMIT 10
        """

        rows = run_query(query, params)

        return {
            "tool_name": "ask_database_custom_question",
            "tenant_id": tenant_id,
            "company_id": company_id,
            "question": question,
            "query_type": "top_overdue_customers",
            "results": [
                {
                    "partner_id": row.get("partner_id"),
                    "customer": row.get("partner_name"),
                    "company_id": row.get("company_id"),
                    "company": row.get("company_name"),
                    "overdue_amount": float(row.get("overdue_amount") or 0),
                    "overdue_invoice_count": int(row.get("overdue_invoice_count") or 0),
                    "max_days_overdue": int(row.get("max_days_overdue") or 0),
                }
                for row in rows
            ],
            "note": "Real data from PostgreSQL fact_account_moves.",
        }

    # 5. Inventory value by company
    if any(word in text for word in [
        "inventory value by company",
        "stock value by company",
        "which company has most inventory",
    ]):
        query = """
        SELECT
            q.company_id,
            q.company_name,
            COALESCE(SUM(q.available_quantity * COALESCE(p.standard_price, 0)), 0) AS inventory_value,
            COUNT(DISTINCT q.product_id) AS sku_count,
            COALESCE(SUM(q.available_quantity), 0) AS available_quantity
        FROM fact_stock_quants q
        LEFT JOIN dim_products p
            ON p.tenant_id = q.tenant_id
           AND p.odoo_id = q.product_id
        WHERE q.tenant_id = :tenant_id
          AND q.available_quantity > 0
        """

        if company_id is not None:
            query += " AND q.company_id = :company_id"
            params["company_id"] = company_id

        query += """
        GROUP BY q.company_id, q.company_name
        ORDER BY inventory_value DESC
        """

        rows = run_query(query, params)

        return {
            "tool_name": "ask_database_custom_question",
            "tenant_id": tenant_id,
            "company_id": company_id,
            "question": question,
            "query_type": "inventory_value_by_company",
            "results": [
                {
                    "company_id": row.get("company_id"),
                    "company": row.get("company_name"),
                    "inventory_value": float(row.get("inventory_value") or 0),
                    "sku_count": int(row.get("sku_count") or 0),
                    "available_quantity": float(row.get("available_quantity") or 0),
                }
                for row in rows
            ],
            "note": "Real data from PostgreSQL fact_stock_quants and dim_products.",
        }

    return {
        "tool_name": "ask_database_custom_question",
        "tenant_id": tenant_id,
        "company_id": company_id,
        "question": question,
        "status": "unsupported_question",
        "message": (
            "This custom database question is not supported yet in the safe SQL mapper. "
            "Supported examples: sales by company, orders by state, revenue by month, overdue customers, inventory value by company."
        ),
        "results": [],
        "note": "No SQL was executed because the question did not match a safe predefined query.",
    }



def generate_report_tool(
    tenant_id: str,
    company_id: int | None = None,
    report_type: str = "business_summary",
) -> dict:
    """
    Generate a PDF business report using real PostgreSQL-backed tools.

    This tool prepares a simple CFO-style PDF report.
    """

    reports_dir = Path("reports")
    reports_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"business_report_{tenant_id}_{timestamp}.pdf"
    report_path = reports_dir / filename

    # ─────────────────────────────
    # Pull real data from existing tools
    # Each section is independently protected so the report
    # still generates even if some data sources are unavailable.
    # ─────────────────────────────
    try:
        sales = get_sales_summary_tool(
            tenant_id=tenant_id,
            company_id=company_id,
        )
    except Exception:
        sales = {
            "total_revenue": 0, "order_count": 0, "average_order_value": 0,
            "first_order_date": None, "last_order_date": None,
        }

    try:
        top_products = get_top_products_tool(
            tenant_id=tenant_id,
            company_id=company_id,
            limit=5,
        )
    except Exception:
        top_products = {"products": []}

    try:
        cash_flow = get_cash_flow_health_tool(
            tenant_id=tenant_id,
            company_id=company_id,
        )
    except Exception:
        cash_flow = {
            "accounts_receivable": 0, "accounts_payable": 0,
            "liquidity_ratio": 0, "liquidity_status": "Not available",
        }

    try:
        receivables = get_receivables_analysis_tool(
            tenant_id=tenant_id,
            company_id=company_id,
            limit=5,
        )
    except Exception:
        receivables = {
            "total_receivables": 0, "overdue_receivables": 0,
            "open_invoice_count": 0, "overdue_invoice_count": 0,
            "risk_level": "Not available", "top_overdue_customers": [],
        }

    try:
        inventory_efficiency = get_inventory_efficiency_tool(
            tenant_id=tenant_id,
            company_id=company_id,
        )
    except Exception:
        inventory_efficiency = {
            "total_inventory_value": 0, "total_sku_count": 0,
            "turnover_ratio": 0, "days_inventory_on_hand": None,
            "efficiency_rating": "Not available",
        }

    try:
        inventory_alerts = get_inventory_alerts_tool(
            tenant_id=tenant_id,
            company_id=company_id,
        )
    except Exception:
        inventory_alerts = {"low_stock_items": [], "expiring_soon": []}

    try:
        health = get_business_health_score_tool(
            tenant_id=tenant_id,
            company_id=company_id,
        )
    except Exception:
        health = {
            "business_health_score": None,
            "health_status": "Not available",
        }

    # ─────────────────────────────
    # Build report text
    # ─────────────────────────────
    lines = []

    lines.append("DOOVA ONEVIEW - AI FINANCIAL ADVISOR REPORT")
    lines.append("=" * 60)
    lines.append(f"Tenant ID: {tenant_id}")
    lines.append(f"Company ID: {company_id}")
    lines.append(f"Report Type: {report_type}")
    lines.append(f"Generated At: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")

    lines.append("1. BUSINESS HEALTH")
    lines.append("-" * 60)
    lines.append(f"Health Score: {health.get('business_health_score')}")
    lines.append(f"Health Status: {health.get('health_status')}")
    lines.append("")

    lines.append("2. SALES SUMMARY")
    lines.append("-" * 60)
    lines.append(f"Total Revenue: {sales.get('total_revenue')}")
    lines.append(f"Order Count: {sales.get('order_count')}")
    lines.append(f"Average Order Value: {sales.get('average_order_value')}")
    lines.append(f"First Order Date: {sales.get('first_order_date')}")
    lines.append(f"Last Order Date: {sales.get('last_order_date')}")
    lines.append("")

    lines.append("3. TOP PRODUCTS")
    lines.append("-" * 60)

    for index, product in enumerate(top_products.get("products", []), start=1):
        lines.append(
            f"{index}. {product.get('product')} | "
            f"Revenue: {product.get('revenue')} | "
            f"Quantity: {product.get('quantity')}"
        )

    lines.append("")

    lines.append("4. CASH FLOW HEALTH")
    lines.append("-" * 60)
    lines.append(f"Accounts Receivable: {cash_flow.get('accounts_receivable')}")
    lines.append(f"Accounts Payable: {cash_flow.get('accounts_payable')}")
    lines.append(f"Liquidity Ratio: {cash_flow.get('liquidity_ratio')}")
    lines.append(f"Liquidity Status: {cash_flow.get('liquidity_status')}")
    lines.append("")

    lines.append("5. RECEIVABLES ANALYSIS")
    lines.append("-" * 60)
    lines.append(f"Total Receivables: {receivables.get('total_receivables')}")
    lines.append(f"Overdue Receivables: {receivables.get('overdue_receivables')}")
    lines.append(f"Open Invoice Count: {receivables.get('open_invoice_count')}")
    lines.append(f"Overdue Invoice Count: {receivables.get('overdue_invoice_count')}")
    lines.append(f"Risk Level: {receivables.get('risk_level')}")
    lines.append("")

    lines.append("Top Overdue Customers:")
    for index, customer in enumerate(receivables.get("top_overdue_customers", []), start=1):
        lines.append(
            f"{index}. {customer.get('customer')} | "
            f"Overdue: {customer.get('overdue_amount')} | "
            f"Days Overdue: {customer.get('max_days_overdue')}"
        )

    lines.append("")

    lines.append("6. INVENTORY EFFICIENCY")
    lines.append("-" * 60)
    lines.append(f"Total Inventory Value: {inventory_efficiency.get('total_inventory_value')}")
    lines.append(f"Total SKU Count: {inventory_efficiency.get('total_sku_count')}")
    lines.append(f"Turnover Ratio: {inventory_efficiency.get('turnover_ratio')}")
    lines.append(f"Days Inventory On Hand: {inventory_efficiency.get('days_inventory_on_hand')}")
    lines.append(f"Efficiency Rating: {inventory_efficiency.get('efficiency_rating')}")
    lines.append("")

    lines.append("7. INVENTORY ALERTS")
    lines.append("-" * 60)
    low_stock_items = inventory_alerts.get("low_stock_items", [])
    lines.append(f"Low Stock Item Count: {len(low_stock_items)}")

    for index, item in enumerate(low_stock_items[:10], start=1):
        lines.append(
            f"{index}. {item.get('product')} | "
            f"Available: {item.get('available')} | "
            f"Location: {item.get('location')}"
        )

    lines.append("")
    lines.append("NOTE")
    lines.append("-" * 60)
    lines.append("This report uses real data synced from Odoo into PostgreSQL.")
    lines.append("Currency is currently marked as unknown unless configured in the data layer.")

    report_text = "\n".join(lines)

    # ─────────────────────────────
    # Generate PDF
    # ─────────────────────────────
    c = canvas.Canvas(str(report_path), pagesize=letter)
    width, height = letter

    y = height - 40
    line_height = 14

    for line in lines:
        c.drawString(40, y, str(line)[:110])
        y -= line_height

        if y < 40:
            c.showPage()
            y = height - 40

    c.save()

    return {
        "tool_name": "generate_report_tool",
        "tenant_id": tenant_id,
        "company_id": company_id,
        "report_type": report_type,
        "report_ready": True,
        "report_path": str(report_path),
        "report_filename": filename,
        "download_url": f"{AgentConfig.API_BASE_URL}/reports/{filename}",
        "summary": {
            "total_revenue": sales.get("total_revenue"),
            "business_health_score": health.get("business_health_score"),
            "health_status": health.get("health_status"),
            "liquidity_status": cash_flow.get("liquidity_status"),
            "receivables_risk": receivables.get("risk_level"),
            "inventory_efficiency": inventory_efficiency.get("efficiency_rating"),
            "low_stock_count": len(low_stock_items),
        },
        "note": "PDF report generated from real PostgreSQL-backed Odoo data.",
    }


def send_alert_tool(
    tenant_id: str,
    title: str,
    message: str,
    severity: str = "info",
    company_id: int | None = None,
    source_tool: str | None = None,
) -> dict:
    """
    Safe alert tool.

    First version:
    - Does NOT send real push notifications.
    - Returns a structured alert object.
    - Later this can be saved to a notifications table or sent to frontend.
    """

    from datetime import datetime
    from uuid import uuid4

    allowed_severities = ["info", "warning", "critical", "success"]

    if severity not in allowed_severities:
        severity = "info"

    alert = {
        "alert_id": str(uuid4()),
        "tenant_id": tenant_id,
        "company_id": company_id,
        "title": title,
        "message": message,
        "severity": severity,
        "source_tool": source_tool,
        "created_at": datetime.now().isoformat(),
        "status": "prepared",
    }

    return {
        "tool_name": "send_alert_tool",
        "alert": alert,
        "sent": False,
        "note": (
            "Alert prepared successfully. This first version does not send a real notification yet. "
            "It can later be connected to a notifications table or frontend notification system."
        ),
    }



def send_email_tool(
    tenant_id: str,
    to_email: str,
    subject: str,
    body: str,
    company_id: int | None = None,
    source_tool: str | None = None,
) -> dict:
    """
    Safe email tool.

    First version:
    - Does NOT send a real email.
    - Prepares an email object only.
    - Later this can be connected to SMTP, SendGrid, Gmail API, or Odoo mail.
    """

    from datetime import datetime
    from uuid import uuid4
    import re

    email_pattern = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"

    if not re.match(email_pattern, to_email):
        return {
            "tool_name": "send_email_tool",
            "sent": False,
            "status": "invalid_email",
            "message": "Invalid recipient email address.",
            "email": None,
        }

    email = {
        "email_id": str(uuid4()),
        "tenant_id": tenant_id,
        "company_id": company_id,
        "to_email": to_email,
        "subject": subject,
        "body": body,
        "source_tool": source_tool,
        "created_at": datetime.now().isoformat(),
        "status": "prepared",
    }

    return {
        "tool_name": "send_email_tool",
        "email": email,
        "sent": False,
        "note": (
            "Email prepared successfully. This first version does not send a real email yet. "
            "It can later be connected to SMTP, SendGrid, Gmail API, or Odoo mail."
        ),
    }


def get_last_report_tool(
    tenant_id: str,
    company_id: int | None = None,
) -> dict:
    """
    Find the most recent PDF report for this tenant and provide a download link.
    """
    reports_dir = Path("reports")
    if not reports_dir.exists():
        return {"status": "no_reports", "message": "No reports directory found."}

    # Match files like business_report_{tenant_id}_*.pdf
    pattern = f"business_report_{tenant_id}_*.pdf"
    files = list(reports_dir.glob(pattern))

    if not files:
        return {"status": "no_reports", "message": f"No reports found for tenant {tenant_id}."}

    # Sort by creation time (newest first)
    files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
    last_file = files[0]
    filename = last_file.name

    return {
        "tool_name": "get_last_report_tool",
        "tenant_id": tenant_id,
        "filename": filename,
        "download_url": f"{AgentConfig.API_BASE_URL}/reports/{filename}",
        "generated_at": datetime.fromtimestamp(last_file.stat().st_mtime).isoformat(),
        "status": "success",
        "message": f"Found the most recent report: {filename}",
    }