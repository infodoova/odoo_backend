from typing import Optional
# api/agent/tools_refactored/common.py

import re
from pathlib import Path
from datetime import datetime
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from ..db import run_query
from ..query_context import extract_date_range, normalize_company_ids, build_company_filter_sql, build_tenant_filter_sql
from ..config import AgentConfig

def get_companies_tool(tenant_id: str, tenant_ids: Optional[list[str]] = None) -> dict:
    t_sql_def, t_params_def = build_tenant_filter_sql(tenant_id, tenant_ids, column_name="tenant_id", prefix="t_def")
    rows = run_query(f"SELECT id, name FROM dim_companies WHERE 1=1 {t_sql_def}", t_params_def)
    return {"tool_name": "get_companies_tool", "companies": rows}

def resolve_company_name(tenant_id: str, company_id: int | None = None) -> str:
    if not company_id:
        return "All Companies"
    try:
        rows = run_query("SELECT name FROM dim_companies WHERE id = %(cid)s LIMIT 1", {"cid": int(company_id)})
        if rows and rows[0].get("name"):
            return rows[0]["name"]
    except Exception:
        pass
    return f"Company {company_id}"

def get_tenant_profile_tool(tenant_id: str, company_id: int | None = None, company_ids: Optional[list[int]] = None, tenant_ids: Optional[list[str]] = None) -> dict:
    """Fetches the company's industry, sector, and operational context from the database."""
    # dim_companies PK is "id", not "company_id"
    company_f_sql, company_f_params = build_company_filter_sql(tenant_id, normalize_company_ids(company_id=company_id, companies=company_ids), column_name="id")
    t_sql_def, t_params_def = build_tenant_filter_sql(tenant_id, tenant_ids, column_name="tenant_id", prefix="t_def")
    company_params = {**company_f_params, **t_params_def}

    # Try to get basic company info
    rows = run_query(
        f"""SELECT
                name,
                'Not Specified' AS industry,
                'Not Specified' AS company_type,
                COALESCE(currency_name, currency_code, 'USD') AS currency
            FROM dim_companies
            WHERE 1=1 {t_sql_def} {company_f_sql}
            LIMIT 5""",
        company_params,
    )

    # 1. Dynamic Catalog Study (Group by ANY product_type in database)
    cat_rows = run_query(
        f"""SELECT
                COALESCE(product_type, 'unclassified') AS ptype,
                COUNT(DISTINCT id) AS sku_count
            FROM dim_products
            WHERE 1=1 {t_sql_def}
            GROUP BY COALESCE(product_type, 'unclassified')""",
        t_params_def,
    )
    catalog_by_type = {r["ptype"]: int(r["sku_count"]) for r in cat_rows}
    total_skus = sum(catalog_by_type.values())

    # 2. Dynamic Transaction & Revenue Study (Group by ANY product_type in database)
    t_sql_l, t_params_l = build_tenant_filter_sql(tenant_id, tenant_ids, column_name="l.tenant_id", prefix="t_l")
    rev_rows = run_query(
        f"""SELECT
                COALESCE(p.product_type, 'unclassified') AS ptype,
                COUNT(DISTINCT l.id) AS line_count,
                COALESCE(SUM(l.price_subtotal), 0) AS total_revenue
            FROM fact_sales_order_lines l
            JOIN dim_products p ON l.product_id = p.id AND l.tenant_id = p.tenant_id
            JOIN fact_sales_orders o ON l.sales_order_id = o.id AND l.tenant_id = o.tenant_id
            WHERE 1=1 {t_sql_l} AND o.state IN ('sale', 'done')
            GROUP BY COALESCE(p.product_type, 'unclassified')
            ORDER BY total_revenue DESC""",
        t_params_l,
    )

    # 3. Dynamic Category Study (Top Product Categories by Revenue)
    cat_rev_rows = run_query(
        f"""SELECT
                COALESCE(c.complete_name, c.name, 'Uncategorized') AS category_name,
                COALESCE(SUM(l.price_subtotal), 0) AS category_revenue,
                COUNT(DISTINCT l.id) AS category_lines
            FROM fact_sales_order_lines l
            JOIN dim_products p ON l.product_id = p.id AND l.tenant_id = p.tenant_id
            JOIN fact_sales_orders o ON l.sales_order_id = o.id AND l.tenant_id = o.tenant_id
            LEFT JOIN dim_product_categories c ON p.category_id = c.id AND p.tenant_id = c.tenant_id
            WHERE 1=1 {t_sql_l} AND o.state IN ('sale', 'done')
            GROUP BY COALESCE(c.complete_name, c.name, 'Uncategorized')
            ORDER BY category_revenue DESC
            LIMIT 5""",
        t_params_l,
    )

    total_revenue = sum(float(r["total_revenue"]) for r in rev_rows)
    total_lines = sum(int(r["line_count"]) for r in rev_rows)

    type_study = []
    for r in rev_rows:
        ptype = r["ptype"]
        rev = float(r["total_revenue"])
        lines = int(r["line_count"])
        skus = catalog_by_type.get(ptype, 0)
        pct = round((rev / total_revenue * 100), 1) if total_revenue > 0 else 0.0
        line_pct = round((lines / total_lines * 100), 1) if total_lines > 0 else 0.0
        type_study.append({
            "product_type": ptype,
            "revenue": rev,
            "revenue_share_pct": f"{pct}%",
            "order_line_count": lines,
            "order_line_share_pct": f"{line_pct}%",
            "catalog_sku_count": skus
        })

    # Dynamic Classification Label from Top Revenue Driver
    if type_study and total_revenue > 0:
        top_driver = type_study[0]
        top_type = top_driver["product_type"].upper()
        top_pct = top_driver["revenue_share_pct"]
        inferred_type = f"Dynamic {top_type}-Dominant Business ({top_pct} Revenue Share)"
        primary_driver = f"Top revenue driver: '{top_type}' generates {top_driver['revenue_share_pct']} of total revenue across {top_driver['order_line_count']} order lines."
    else:
        top_sku_type = max(catalog_by_type.items(), key=lambda x: x[1])[0] if catalog_by_type else "unclassified"
        inferred_type = f"Dynamic {top_sku_type.upper()}-Weighted Catalog Model"
        primary_driver = f"No sales transactions yet. Catalog is lead by '{top_sku_type}' ({catalog_by_type.get(top_sku_type, 0)} SKUs)."

    return {
        "tool_name": "get_tenant_profile_tool",
        "companies": [
            {"name": r.get('name'), "industry": r.get('industry'), "type": r.get('company_type'), "currency": r.get('currency')}
            for r in rows
        ],
        "inferred_business_model": inferred_type,
        "primary_revenue_driver": primary_driver,
        "dynamic_revenue_study": {
            "total_revenue_analyzed": total_revenue,
            "total_sales_lines_analyzed": total_lines,
            "total_catalog_skus": total_skus,
            "product_type_breakdown": type_study,
            "top_product_categories": [
                {
                    "category": r["category_name"],
                    "revenue": float(r["category_revenue"]),
                    "revenue_share_pct": f"{round(float(r['category_revenue']) / total_revenue * 100, 1)}%" if total_revenue > 0 else "0%",
                    "line_count": int(r["category_lines"])
                } for r in cat_rev_rows
            ]
        }
    }

def normalize_business_text_for_intent(message: str | None) -> str:
    """
    Lightweight intent normalizer to fix typos and map phrases using exact word matching.
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

    words = text.split()
    cleaned = [replacements.get(w, w) for w in words]
    return " ".join(cleaned)

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

def build_currency_case_sql(column: str, tenant_id: str, base_currency: str | None, currency_column: str = "currency_code", tenant_ids: Optional[list[str]] = None) -> str:
    """Builds a dynamic SQL CASE WHEN block to apply currency conversion to a column."""
    if not base_currency:
        return column

    try:
        from doova_one_view.api.kpi.service import _get_rate_map
        rate_map = _get_rate_map(tenant_id=tenant_id)
        
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
            factor = target_rate / row_rate
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



def build_currency_case_sql(column: str, tenant_id: str, base_currency: str | None, currency_column: str = "currency_code", tenant_ids: Optional[list[str]] = None) -> str:
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

def get_per_tenant_exchange_rates(tenant_ids: Optional[list[str]] = None) -> dict:
    """Returns a dictionary mapping each tenant (by name/id) to its base currency and tenant-relative exchange rates."""
    try:
        from odoo_app.models.tenant import Tenant
        from doova_one_view.api.agent.utils import get_tenant_currency
        from doova_one_view.api.kpi.service import _get_rate_map, _get_conversion_rate
        
        if tenant_ids:
            tenants = list(Tenant.objects.filter(id__in=tenant_ids))
        else:
            tenants = list(Tenant.objects.all())
            
        result = {}
        for t in tenants:
            tid_str = str(t.id)
            base_curr = get_tenant_currency(tid_str)
            raw_rates = _get_rate_map(tid_str)
            
            # Ensure base currency is in raw_rates
            if base_curr and base_curr not in raw_rates:
                raw_rates[base_curr] = 1.0
                
            tenant_rates = {}
            for target_curr in raw_rates.keys():
                if target_curr != base_curr:
                    conv = _get_conversion_rate(base_curr, target_curr, raw_rates)
                    tenant_rates[target_curr] = round(conv, 6)
            
            result[t.name] = {
                "tenant_id": tid_str,
                "base_currency": base_curr,
                "exchange_rates": tenant_rates
            }
        return result
    except Exception as e:
        import logging
        logging.error(f"Error building per tenant exchange rates: {e}")
        return {}

def get_multi_currency_conversions(
    amount: float, 
    tenant_id: str | None, 
    company_id: int | None = None, 
    company_ids: list[int] | None = None, 
    base_currency: str | None = None, 
    tenant_ids: Optional[list[str]] = None,
    start_date: str | None = None,
    end_date: str | None = None,
    domain: str = "sales",
) -> dict:
    """Returns a dictionary mapping all active system currency codes, per-tenant exchange rates, and converted amounts across multi-tenant/multi-company contexts."""
    try:
        from doova_one_view.api.agent.utils import get_tenant_currency
        from doova_one_view.api.kpi.service import _get_rate_map, _get_conversion_rate

        selected_cids = normalize_company_ids(company_id=company_id, companies=company_ids)
        target_cid = selected_cids[0] if len(selected_cids) == 1 else None

        native_curr = base_currency or get_tenant_currency(tenant_id, company_id=target_cid, company_ids=selected_cids)
        rate_map = _get_rate_map(tenant_id=tenant_id)
        
        per_tenant_rates = get_per_tenant_exchange_rates(tenant_ids=tenant_ids)
        
        conversions = {}
        applied_rates = {}

        # If multiple companies (or all companies) are involved, perform 2-step per-company conversion & sum matching KPI _sum_converted pattern
        if len(selected_cids) != 1 and not base_currency:
            table_name = "fact_sales_orders"
            state_filter = "state IN ('sale', 'done')"
            date_col = "date_order"
            amount_col_name = "amount_total"
            if domain == "purchasing":
                table_name = "fact_purchase_orders"
                state_filter = "state IN ('purchase', 'done')"
                date_col = "date_order"
                amount_col_name = "amount_total"
            elif domain == "finance":
                table_name = "fact_account_moves"
                state_filter = "state = 'posted'"
                date_col = "date"
                amount_col_name = "amount_total"

            t_sql_def, t_params_def = build_tenant_filter_sql(tenant_id, tenant_ids, column_name="t.tenant_id", prefix="t_multi")
            f_sql_def, f_params_def = build_company_filter_sql(tenant_id, selected_cids, column_name="t.company_id", prefix="c_multi")
            
            comp_query = f"""
                SELECT COALESCE(t.currency_code, c.currency_name, c.currency_code, 'XAF') AS currency_code, COALESCE(SUM(t.{amount_col_name}), 0) AS raw_total
                FROM {table_name} t
                LEFT JOIN dim_companies c ON t.company_id = c.id
                WHERE 1=1 {t_sql_def} {f_sql_def} AND {state_filter}
            """
            params = {**t_params_def, **f_params_def}
            if start_date:
                comp_query += f" AND t.{date_col} >= :start_date"
                params["start_date"] = start_date
            if end_date:
                comp_query += f" AND t.{date_col} <= :end_date"
                params["end_date"] = end_date
            comp_query += " GROUP BY COALESCE(t.currency_code, c.currency_name, c.currency_code, 'XAF')"
            
            comp_rows = run_query(comp_query, params)
            
            target_currencies = list(rate_map.keys())
            if native_curr and native_curr not in target_currencies:
                target_currencies.append(native_curr)
                
            multi_totals = {tc: 0.0 for tc in target_currencies}
            for r in comp_rows:
                ccurr = r.get("currency_code") or "XAF"
                crev = float(r.get("raw_total") or 0.0)
                for tc in target_currencies:
                    crate = _get_conversion_rate(ccurr, tc, rate_map)
                    multi_totals[tc] += crev * crate

            for tc, tot in multi_totals.items():
                conversions[tc] = round(tot, 2)
                conv_rate = _get_conversion_rate(native_curr, tc, rate_map)
                applied_rates[tc] = round(conv_rate, 6)
        else:
            if native_curr:
                conversions[native_curr] = round(amount, 2)
                applied_rates[native_curr] = 1.0
                for target_curr in rate_map.keys():
                    if target_curr != native_curr:
                        conv_rate = _get_conversion_rate(native_curr, target_curr, rate_map)
                        conversions[target_curr] = round(amount * conv_rate, 2)
                        applied_rates[target_curr] = round(conv_rate, 6)

        return {
            "tenant_currency": native_curr,
            "conversions": conversions,
            "applied_exchange_rates": applied_rates,
            "tenant_rates_breakdown": per_tenant_rates,
        }
    except Exception as e:
        import logging
        logging.error(f"Error in get_multi_currency_conversions: {e}")
        return {}
