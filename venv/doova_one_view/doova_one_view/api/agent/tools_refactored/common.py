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

    # Infer business type from product and transaction data (tenant-scoped only, no company filter)
    product_stats = run_query(
        f"""SELECT
                COUNT(DISTINCT CASE WHEN product_type = 'product' THEN id END) AS physical_products,
                COUNT(DISTINCT CASE WHEN product_type = 'service' THEN id END) AS services,
                COUNT(DISTINCT CASE WHEN product_type = 'consu' THEN id END) AS consumables
            FROM dim_products
            WHERE 1=1 {t_sql_def}""",
        t_params_def,
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
            {"name": r.get('name'), "industry": r.get('industry'), "type": r.get('company_type'), "currency": r.get('currency')}
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

def get_companies_tool(tenant_id: str, tenant_ids: Optional[list[str]] = None) -> dict:
    t_sql_def, t_params_def = build_tenant_filter_sql(tenant_id, tenant_ids, column_name="tenant_id", prefix="t_def")
    rows = run_query(f"SELECT id, name FROM dim_companies WHERE 1=1 {t_sql_def}", t_params_def)
    return {"tool_name": "get_companies_tool", "companies": rows}

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

    # Infer business type from product and transaction data (tenant-scoped only, no company filter)
    product_stats = run_query(
        f"""SELECT
                COUNT(DISTINCT CASE WHEN product_type = 'product' THEN id END) AS physical_products,
                COUNT(DISTINCT CASE WHEN product_type = 'service' THEN id END) AS services,
                COUNT(DISTINCT CASE WHEN product_type = 'consu' THEN id END) AS consumables
            FROM dim_products
            WHERE 1=1 {t_sql_def}""",
        t_params_def,
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
            {"name": r.get('name'), "industry": r.get('industry'), "type": r.get('company_type'), "currency": r.get('currency')}
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
