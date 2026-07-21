# api/agent/tools_refactored/purchasing.py

"""
Purchasing Intelligence Tools — 7 tools covering the entire procurement domain.

Tools:
  1. get_purchase_summary_tool        — total spend, PO count, avg PO value
  2. get_top_vendors_tool             — vendors ranked by spend
  3. get_vendor_performance_tool      — delivery metrics per vendor
  4. get_procurement_category_breakdown_tool — spend by product category
  5. get_purchase_vs_sales_margin_tool — buy vs sell price analysis
  6. get_po_fulfillment_tool          — overdue/partial POs
  7. get_purchase_trend_tool          — monthly spend time series
"""

from .common import (
    run_query,
    normalize_company_ids,
    build_company_filter_sql,
    calculate_ratio,
    build_currency_case_sql,
)


# ──────────────────────────────────────────────
# 1. PURCHASE SUMMARY
# ──────────────────────────────────────────────

def get_purchase_summary_tool(
    tenant_id: str,
    company_id: int | None = None,
    company_ids: list[int] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    base_currency: str | None = None,
) -> dict:
    """Total confirmed purchase spend, PO count, and average PO value."""
    selected = normalize_company_ids(company_id=company_id, companies=company_ids)
    amount_col = build_currency_case_sql('amount_total', tenant_id, base_currency)
    params: dict = {"tenant_id": tenant_id}
    f_sql, f_params = build_company_filter_sql(tenant_id, selected)
    params.update(f_params)

    date_sql = ""
    if start_date:
        date_sql += " AND date_order >= :start_date"
        params["start_date"] = start_date
    if end_date:
        date_sql += " AND date_order <= :end_date"
        params["end_date"] = end_date

    rows = run_query(
        f"""SELECT
                COALESCE(SUM({amount_col}), 0)  AS total_spend,
                COUNT(*)                        AS po_count,
                COALESCE(AVG({amount_col}), 0)  AS avg_po_value,
                COALESCE(MIN(date_order), NULL) AS first_po_date,
                COALESCE(MAX(date_order), NULL) AS last_po_date
            FROM fact_purchase_orders
            WHERE tenant_id = :tenant_id
              AND state IN ('purchase', 'done')
              {f_sql} {date_sql}""",
        params,
    )

    row = rows[0] if rows else {}
    return {
        "tool_name": "get_purchase_summary_tool",
        "total_spend": float(row.get("total_spend") or 0),
        "po_count": int(row.get("po_count") or 0),
        "avg_po_value": round(float(row.get("avg_po_value") or 0), 2),
        "first_po_date": str(row.get("first_po_date") or ""),
        "last_po_date": str(row.get("last_po_date") or ""),
    }


# ──────────────────────────────────────────────
# 2. TOP VENDORS BY SPEND
# ──────────────────────────────────────────────

def get_top_vendors_tool(
    tenant_id: str,
    company_id: int | None = None,
    company_ids: list[int] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 10,
    base_currency: str | None = None,
) -> dict:
    """Rank vendors by total confirmed purchase spend."""
    selected = normalize_company_ids(company_id=company_id, companies=company_ids)
    amount_col = build_currency_case_sql(
        'po.amount_total', tenant_id, base_currency, 'po.currency_code'
    )
    params: dict = {"tenant_id": tenant_id, "limit": limit}
    f_sql, f_params = build_company_filter_sql(
        tenant_id, selected, column_name="po.company_id"
    )
    params.update(f_params)

    date_sql = ""
    if start_date:
        date_sql += " AND po.date_order >= :start_date"
        params["start_date"] = start_date
    if end_date:
        date_sql += " AND po.date_order <= :end_date"
        params["end_date"] = end_date

    rows = run_query(
        f"""SELECT
                p.name                           AS vendor_name,
                COALESCE(SUM({amount_col}), 0)   AS total_spend,
                COUNT(*)                         AS po_count,
                COALESCE(AVG({amount_col}), 0)   AS avg_po_value
            FROM fact_purchase_orders po
            JOIN dim_partners p
              ON po.partner_id = p.id AND po.tenant_id = p.tenant_id
            WHERE po.tenant_id = :tenant_id
              AND po.state IN ('purchase', 'done')
              {f_sql} {date_sql}
            GROUP BY p.name
            ORDER BY total_spend DESC
            LIMIT :limit""",
        params,
    )

    return {
        "tool_name": "get_top_vendors_tool",
        "vendors": [
            {
                "vendor": r.get("vendor_name"),
                "total_spend": float(r.get("total_spend")),
                "po_count": int(r.get("po_count")),
                "avg_po_value": round(float(r.get("avg_po_value")), 2),
            }
            for r in rows
        ],
    }


# ──────────────────────────────────────────────
# 3. VENDOR PERFORMANCE SCORECARD
# ──────────────────────────────────────────────

def get_vendor_performance_tool(
    tenant_id: str,
    company_id: int | None = None,
    company_ids: list[int] | None = None,
    limit: int = 10,
    base_currency: str | None = None,
) -> dict:
    """Per-vendor on-time delivery rate and average lead time."""
    selected = normalize_company_ids(company_id=company_id, companies=company_ids)
    amount_col = build_currency_case_sql(
        'po.amount_total', tenant_id, base_currency, 'po.currency_code'
    )
    params: dict = {"tenant_id": tenant_id, "limit": limit}
    f_sql, f_params = build_company_filter_sql(
        tenant_id, selected, column_name="po.company_id"
    )
    params.update(f_params)

    # Join POs to incoming pickings via `origin` (contains PO name like 'P00015')
    rows = run_query(
        f"""SELECT
                p.name AS vendor_name,
                COALESCE(SUM({amount_col}), 0) AS total_spend,
                COUNT(DISTINCT po.id) AS po_count,
                -- Delivery metrics from incoming pickings linked via origin
                COUNT(DISTINCT sp.id) AS receipts_total,
                COUNT(DISTINCT sp.id)
                    FILTER (WHERE sp.state = 'done'
                            AND sp.date_done <= sp.scheduled_date) AS receipts_on_time,
                COALESCE(
                    AVG(EXTRACT(EPOCH FROM (sp.date_done - po.date_order)) / 86400)
                    FILTER (WHERE sp.state = 'done'),
                    0
                ) AS avg_lead_time_days
            FROM fact_purchase_orders po
            JOIN dim_partners p
              ON po.partner_id = p.id AND po.tenant_id = p.tenant_id
            LEFT JOIN fact_stock_pickings sp
              ON sp.origin = po.odoo_name
              AND sp.tenant_id = po.tenant_id
              AND sp.picking_type = 'incoming'
            WHERE po.tenant_id = :tenant_id
              AND po.state IN ('purchase', 'done')
              {f_sql}
            GROUP BY p.name
            ORDER BY total_spend DESC
            LIMIT :limit""",
        params,
    )

    vendors = []
    for r in rows:
        total_receipts = int(r.get("receipts_total") or 0)
        on_time = int(r.get("receipts_on_time") or 0)
        on_time_pct = round(calculate_ratio(on_time, total_receipts) * 100, 1) if total_receipts > 0 else None
        vendors.append(
            {
                "vendor": r.get("vendor_name"),
                "total_spend": float(r.get("total_spend")),
                "po_count": int(r.get("po_count")),
                "receipts_total": total_receipts,
                "on_time_delivery_pct": on_time_pct,
                "avg_lead_time_days": round(float(r.get("avg_lead_time_days") or 0), 1),
            }
        )

    return {
        "tool_name": "get_vendor_performance_tool",
        "vendors": vendors,
    }


# ──────────────────────────────────────────────
# 4. PROCUREMENT SPEND BY CATEGORY
# ──────────────────────────────────────────────

def get_procurement_category_breakdown_tool(
    tenant_id: str,
    company_id: int | None = None,
    company_ids: list[int] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 20,
    base_currency: str | None = None,
) -> dict:
    """Break down purchase spend by product category."""
    selected = normalize_company_ids(company_id=company_id, companies=company_ids)
    price_col = build_currency_case_sql(
        'l.price_subtotal', tenant_id, base_currency, 'po.currency_code'
    )
    params: dict = {"tenant_id": tenant_id, "limit": limit}
    f_sql, f_params = build_company_filter_sql(
        tenant_id, selected, column_name="po.company_id"
    )
    params.update(f_params)

    date_sql = ""
    if start_date:
        date_sql += " AND po.date_order >= :start_date"
        params["start_date"] = start_date
    if end_date:
        date_sql += " AND po.date_order <= :end_date"
        params["end_date"] = end_date

    rows = run_query(
        f"""SELECT
                COALESCE(c.complete_name, c.name, 'Uncategorized') AS category,
                COALESCE(SUM({price_col}), 0)  AS spend,
                COUNT(DISTINCT l.id)           AS line_count
            FROM fact_purchase_order_lines l
            JOIN fact_purchase_orders po
              ON l.purchase_order_id = po.id AND l.tenant_id = po.tenant_id
            LEFT JOIN dim_products p
              ON l.product_id = p.id AND l.tenant_id = p.tenant_id
            LEFT JOIN dim_product_categories c
              ON p.category_id = c.id AND p.tenant_id = c.tenant_id
            WHERE l.tenant_id = :tenant_id
              AND po.state IN ('purchase', 'done')
              {f_sql} {date_sql}
            GROUP BY COALESCE(c.complete_name, c.name, 'Uncategorized')
            ORDER BY spend DESC
            LIMIT :limit""",
        params,
    )

    total = sum(float(r.get("spend")) for r in rows)
    return {
        "tool_name": "get_procurement_category_breakdown_tool",
        "total_spend": total,
        "categories": [
            {
                "category": r.get("category"),
                "spend": float(r.get("spend")),
                "pct_of_total": round(calculate_ratio(float(r.get("spend")), total) * 100, 1),
                "line_count": int(r.get("line_count")),
            }
            for r in rows
        ],
    }


# ──────────────────────────────────────────────
# 5. PURCHASE vs SALES MARGIN ANALYSIS
# ──────────────────────────────────────────────

def get_purchase_vs_sales_margin_tool(
    tenant_id: str,
    company_id: int | None = None,
    company_ids: list[int] | None = None,
    limit: int = 20,
    base_currency: str | None = None,
) -> dict:
    """Compare average buy price vs average sell price per product."""
    selected = normalize_company_ids(company_id=company_id, companies=company_ids)
    params: dict = {"tenant_id": tenant_id, "limit": limit}
    f_sql_po, f_params_po = build_company_filter_sql(
        tenant_id, selected, column_name="po.company_id", prefix="po_co"
    )
    f_sql_so, f_params_so = build_company_filter_sql(
        tenant_id, selected, column_name="so.company_id", prefix="so_co"
    )
    params.update(f_params_po)
    params.update(f_params_so)

    rows = run_query(
        f"""WITH buy AS (
                SELECT
                    pl.product_id,
                    AVG(pl.price_unit)                AS avg_buy_price,
                    SUM(pl.product_qty)               AS total_qty_bought
                FROM fact_purchase_order_lines pl
                JOIN fact_purchase_orders po
                  ON pl.purchase_order_id = po.id AND pl.tenant_id = po.tenant_id
                WHERE pl.tenant_id = :tenant_id
                  AND po.state IN ('purchase', 'done')
                  AND pl.product_id IS NOT NULL
                  {f_sql_po}
                GROUP BY pl.product_id
            ),
            sell AS (
                SELECT
                    sl.product_id,
                    AVG(sl.price_unit)                AS avg_sell_price,
                    SUM(sl.product_uom_qty)           AS total_qty_sold
                FROM fact_sales_order_lines sl
                JOIN fact_sales_orders so
                  ON sl.sales_order_id = so.id AND sl.tenant_id = so.tenant_id
                WHERE sl.tenant_id = :tenant_id
                  AND so.state IN ('sale', 'done')
                  AND sl.product_id IS NOT NULL
                  {f_sql_so}
                GROUP BY sl.product_id
            )
            SELECT
                p.name           AS product_name,
                b.avg_buy_price,
                s.avg_sell_price,
                b.total_qty_bought,
                s.total_qty_sold
            FROM buy b
            JOIN sell s ON b.product_id = s.product_id
            JOIN dim_products p ON b.product_id = p.id AND p.tenant_id = :tenant_id
            ORDER BY (s.avg_sell_price - b.avg_buy_price) * LEAST(b.total_qty_bought, s.total_qty_sold) DESC
            LIMIT :limit""",
        params,
    )

    products = []
    for r in rows:
        buy = float(r.get("avg_buy_price") or 0)
        sell = float(r.get("avg_sell_price") or 0)
        margin = sell - buy
        margin_pct = round(calculate_ratio(margin, sell) * 100, 1) if sell else 0
        products.append(
            {
                "product": r.get("product_name"),
                "avg_buy_price": round(buy, 2),
                "avg_sell_price": round(sell, 2),
                "margin": round(margin, 2),
                "margin_pct": margin_pct,
                "qty_bought": float(r.get("total_qty_bought") or 0),
                "qty_sold": float(r.get("total_qty_sold") or 0),
            }
        )

    return {
        "tool_name": "get_purchase_vs_sales_margin_tool",
        "products": products,
    }


# ──────────────────────────────────────────────
# 6. PO FULFILLMENT & DELIVERY TRACKING
# ──────────────────────────────────────────────

def get_po_fulfillment_tool(
    tenant_id: str,
    company_id: int | None = None,
    company_ids: list[int] | None = None,
    limit: int = 15,
    base_currency: str | None = None,
) -> dict:
    """Identify overdue POs and partial receipts."""
    selected = normalize_company_ids(company_id=company_id, companies=company_ids)
    amount_col = build_currency_case_sql(
        'po.amount_total', tenant_id, base_currency, 'po.currency_code'
    )
    params: dict = {"tenant_id": tenant_id, "limit": limit}
    f_sql, f_params = build_company_filter_sql(
        tenant_id, selected, column_name="po.company_id"
    )
    params.update(f_params)

    # Overdue POs: past date_planned but not fully received
    overdue_rows = run_query(
        f"""SELECT
                po.odoo_name         AS po_ref,
                p.name               AS vendor_name,
                po.date_planned,
                {amount_col}         AS amount,
                EXTRACT(DAY FROM (CURRENT_TIMESTAMP - po.date_planned)) AS days_overdue
            FROM fact_purchase_orders po
            JOIN dim_partners p
              ON po.partner_id = p.id AND po.tenant_id = p.tenant_id
            WHERE po.tenant_id = :tenant_id
              AND po.state IN ('purchase')
              AND po.date_planned < CURRENT_TIMESTAMP
              {f_sql}
            ORDER BY po.date_planned ASC
            LIMIT :limit""",
        params,
    )

    # Partial receipts: lines where qty_received < product_qty
    partial_rows = run_query(
        f"""SELECT
                po.odoo_name         AS po_ref,
                p.name               AS vendor_name,
                pr.name              AS product_name,
                l.product_qty        AS ordered,
                l.qty_received       AS received,
                (l.product_qty - l.qty_received) AS shortfall
            FROM fact_purchase_order_lines l
            JOIN fact_purchase_orders po
              ON l.purchase_order_id = po.id AND l.tenant_id = po.tenant_id
            JOIN dim_partners p
              ON po.partner_id = p.id AND po.tenant_id = p.tenant_id
            LEFT JOIN dim_products pr
              ON l.product_id = pr.id AND l.tenant_id = pr.tenant_id
            WHERE l.tenant_id = :tenant_id
              AND po.state IN ('purchase', 'done')
              AND l.qty_received < l.product_qty
              AND l.product_qty > 0
              {f_sql}
            ORDER BY shortfall DESC
            LIMIT :limit""",
        params,
    )

    # Summary stats
    summary_rows = run_query(
        f"""SELECT
                COUNT(*) FILTER (WHERE po.state = 'purchase' AND po.date_planned < CURRENT_TIMESTAMP) AS overdue_count,
                COALESCE(SUM({amount_col}) FILTER (WHERE po.state = 'purchase' AND po.date_planned < CURRENT_TIMESTAMP), 0) AS overdue_value,
                COUNT(*) FILTER (WHERE po.state IN ('purchase', 'done')) AS active_count
            FROM fact_purchase_orders po
            WHERE po.tenant_id = :tenant_id
              {f_sql}""",
        params,
    )

    s = summary_rows[0] if summary_rows else {}
    return {
        "tool_name": "get_po_fulfillment_tool",
        "overdue_po_count": int(s.get("overdue_count") or 0),
        "overdue_po_value": float(s.get("overdue_value") or 0),
        "active_po_count": int(s.get("active_count") or 0),
        "overdue_orders": [
            {
                "po_ref": r.get("po_ref"),
                "vendor": r.get("vendor_name"),
                "expected_date": str(r.get("date_planned") or ""),
                "amount": float(r.get("amount") or 0),
                "days_overdue": int(float(r.get("days_overdue") or 0)),
            }
            for r in overdue_rows
        ],
        "partial_receipts": [
            {
                "po_ref": r.get("po_ref"),
                "vendor": r.get("vendor_name"),
                "product": r.get("product_name"),
                "ordered": float(r.get("ordered") or 0),
                "received": float(r.get("received") or 0),
                "shortfall": float(r.get("shortfall") or 0),
            }
            for r in partial_rows
        ],
    }


# ──────────────────────────────────────────────
# 7. PURCHASE TREND (TIME SERIES)
# ──────────────────────────────────────────────

def get_purchase_trend_tool(
    tenant_id: str,
    company_id: int | None = None,
    company_ids: list[int] | None = None,
    granularity: str = "month",
    base_currency: str | None = None,
) -> dict:
    """Purchase spend time series broken down by period."""
    selected = normalize_company_ids(company_id=company_id, companies=company_ids)
    amount_col = build_currency_case_sql('amount_total', tenant_id, base_currency)
    params: dict = {"tenant_id": tenant_id}
    f_sql, f_params = build_company_filter_sql(tenant_id, selected)
    params.update(f_params)

    # Sanitize granularity to prevent SQL injection
    allowed = {"day", "week", "month", "quarter", "year"}
    if granularity not in allowed:
        granularity = "month"

    rows = run_query(
        f"""SELECT
                DATE_TRUNC('{granularity}', date_order) AS period,
                COALESCE(SUM({amount_col}), 0)         AS spend,
                COUNT(*)                               AS po_count
            FROM fact_purchase_orders
            WHERE tenant_id = :tenant_id
              AND state IN ('purchase', 'done')
              AND date_order IS NOT NULL
              {f_sql}
            GROUP BY period
            ORDER BY period ASC""",
        params,
    )

    return {
        "tool_name": "get_purchase_trend_tool",
        "granularity": granularity,
        "points": [
            {
                "period": str(r.get("period")),
                "spend": float(r.get("spend")),
                "po_count": int(r.get("po_count")),
            }
            for r in rows
        ],
    }
