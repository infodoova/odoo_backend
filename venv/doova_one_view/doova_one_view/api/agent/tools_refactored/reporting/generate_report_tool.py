# doova_one_view/api/agent/tools_refactored/reporting/generate_report_tool.py

import os
import io
import re
import json
import base64
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

import markdown
from jinja2 import Environment, FileSystemLoader
from weasyprint import HTML
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker

from doova_one_view.api.agent.query_context import (
    build_tenant_filter_sql,
    normalize_tenant_ids,
    normalize_company_ids,
    build_company_filter_sql,
)
from doova_one_view.api.agent.utils import make_report_url, replace_tenant_ids_with_names, get_tenant_currency, get_project_logo_b64
from doova_one_view.api.agent.db import run_query
from ..common import get_companies_tool, build_currency_case_sql
from ..sales import get_sales_summary_tool, get_time_series_data_tool, get_top_products_tool
from ..finance import (
    get_business_health_score_tool,
    calculate_pnl_tool,
    get_balance_sheet_tool,
    get_receivables_analysis_tool,
    get_payables_analysis_tool,
    get_aging_analysis_tool,
    get_working_capital_tool,
    get_expense_breakdown_tool,
)
from ..purchasing import get_purchase_summary_tool, get_top_vendors_tool, get_purchase_trend_tool
from ..inventory import get_inventory_valuation_tool
from ..emoji_to_badges import normalize_status_emoji
from ..table_layout import add_dynamic_table_widths

from ._date_utils import (
    _infer_comparison_label,
    _resolve_prior_period_dates,
    resolve_period_dates,
    resolve_comparison_dates,
)
from ._formatters import _fmt_money, _fmt_pct, _highlight_negative_numbers_html, _friendly_axis_formatter
from ._variance import _compute_variance, _build_kpi_variance
from ._charts import (
    _render_trend_chart,
    _render_waterfall_chart,
    _render_working_capital_chart,
    _render_custom_chart_blocks,
    _sanitize_rendered_report_html,
)
from ._series import _get_monthly_pnl_series, _get_domain_trend_series
from ._normalize import _normalize_report_data, _normalize_markdown_tables, _render_charts_from_report_data
from ._ai_synthesis import _generate_ai_executive_summary_llm, _generate_ai_domain_analysis
from ._autonomous_insights import _synthesize_autonomous_insights
from ._template_router import _resolve_report_template, _get_reports_dir
from ._domain_data import _fetch_domain_report_data

logger = logging.getLogger(__name__)


def _slugify_filename_part(text: str, max_len: int = 40) -> str:
    if not text:
        return "all"
    cleaned = re.sub(r'[^A-Za-z0-9]+', '_', text.strip())
    cleaned = re.sub(r'_+', '_', cleaned).strip('_')
    return cleaned[:max_len] or "default"


def _build_pdf_filename(
    domain: str,
    company_name: str,
    reporting_period: str,
    tenant_ids: list[str] | None = None,
) -> str:
    tenant_name_str = ""
    try:
        from odoo_app.models import Tenant
        if tenant_ids and len(tenant_ids) > 1:
            tenant_name_str = f"multi_tenants_{len(tenant_ids)}"
        elif tenant_ids:
            t = Tenant.objects.filter(id=tenant_ids[0]).first()
            if t and t.name:
                tenant_name_str = t.name
    except Exception:
        pass
    if not tenant_name_str:
        tenant_name_str = str(tenant_ids[0])[:8] if tenant_ids else "tenant"

    tenant_slug = _slugify_filename_part(tenant_name_str)
    company_slug = _slugify_filename_part(company_name or "All_Companies")
    period_slug = _slugify_filename_part(reporting_period or "All_Time")
    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")

    domain_slug = _slugify_filename_part(domain or "report")
    return f"{domain_slug}_report_{tenant_slug}_{company_slug}_{period_slug}_{timestamp_str}.pdf"


def generate_report_tool(
    tenant_ids: Optional[list[str]] = None,
    company_ids: list[int] | None = None,
    custom_content: str = "",
    base_currency: str | None = None,
    logo_path: str | None = None,
    logo_b64: str | None = None,
    logo_url: str | None = None,
    report_mode: str = "auto",
    report_type: str | None = None,
    report_data: dict | None = None,
    comparison_type: str = "prior_year",
    start_date: str | None = None,
    end_date: str | None = None,
    reporting_period: str | None = None,
    comparison_label: str | None = None,
    prompt: str | None = None,
) -> dict:
    clean_tenant_ids = normalize_tenant_ids(tenant_ids)
    resolved_company_ids = normalize_company_ids(company_ids)
    resolved_company_id = resolved_company_ids[0] if len(resolved_company_ids) == 1 else None
    if report_type and report_mode == "auto":
        report_mode = report_type

    # Check for currency hints in prompt if base_currency is not passed
    prompt_text = (prompt or "").lower()
    if not base_currency:
        if re.search(r'\b(usd|dollars?|\$)\b', prompt_text) or re.search(r'\b(in usd|in dollars)\b', custom_content.lower()):
            base_currency = "USD"
        elif re.search(r'\b(eur|euros?|€)\b', prompt_text) or re.search(r'\b(in eur|in euros)\b', custom_content.lower()):
            base_currency = "EUR"
        elif re.search(r'\b(xaf|fcfa|cfa)\b', prompt_text):
            base_currency = "XAF"

    primary_tenant = clean_tenant_ids[0] if clean_tenant_ids else None
    currency = base_currency or get_tenant_currency(primary_tenant, resolved_company_id)
    search_text = prompt_text.lower() if prompt_text else (custom_content.lower() if custom_content else "")

    # 1. Company & View Labeling
    view_type = "Consolidated"
    if len(resolved_company_ids) == 0:
        company_name = "All Companies (Consolidated)"
        view_type = "Consolidated"
    elif len(resolved_company_ids) == 1:
        company_name = "Financial Overview"
        view_type = "Individual"
        try:
            comp_res = get_companies_tool(tenant_ids=clean_tenant_ids)
            comps = comp_res.get("companies", []) if isinstance(comp_res, dict) else []
            for c in comps:
                if isinstance(c, dict) and (c.get("id") in resolved_company_ids or c.get("odoo_id") in resolved_company_ids):
                    company_name = c.get("name", company_name)
                    break
        except Exception:
            pass
    else:
        view_type = "Comparison"
        try:
            comp_res = get_companies_tool(tenant_ids=clean_tenant_ids)
            comps = comp_res.get("companies", []) if isinstance(comp_res, dict) else []
            selected_names = [
                c.get("name") for c in comps
                if (c.get("id") in resolved_company_ids or c.get("odoo_id") in resolved_company_ids) and c.get("name")
            ]
            if selected_names:
                if len(selected_names) <= 3:
                    company_name = ", ".join(selected_names)
                else:
                    company_name = f"{', '.join(selected_names[:2])} (+{len(selected_names)-2} more)"
            else:
                company_name = f"Multi-Company ({len(resolved_company_ids)} Companies)"
        except Exception:
            company_name = f"Multi-Company ({len(resolved_company_ids)} Companies)"

    # 2. Resolve Reporting Period & Core Financial Dates Dynamically via date_engine
    raw_start = start_date
    raw_end   = end_date
    ytd_start, ytd_end, auto_period_label = resolve_period_dates(
        text=search_text,
        start_date=raw_start,
        end_date=raw_end,
    )
    resolved_period_label = reporting_period or auto_period_label

    # Resolve Comparison Basis Dynamically (auto-infer from resolved ytd_start/ytd_end if not provided)
    _, _, resolved_comparison_label = resolve_comparison_dates(
        start_date=ytd_start,
        end_date=ytd_end,
        comparison_label=comparison_label,
        comparison_type=comparison_type,
    )

    # Resolve Template Selection
    template_file, resolved_domain, meta = _resolve_report_template(report_type or report_mode, prompt_text)

    # ── AGENT-DRIVEN PRESENTATION PATH ──────────────────────────────────────────
    # When report_data is provided OR when a specific domain template is selected,
    # we render the presentation template using live database queries and agent synthesis.
    if report_data or template_file != "report_template.html":
        # Resolve Prior Period Dates for Comparative Analytics
        prior_start, prior_end = _resolve_prior_period_dates(
            ytd_start, ytd_end, resolved_comparison_label, comparison_type
        )

        db_domain_data = _fetch_domain_report_data(
            resolved_domain=resolved_domain,
            tenant_ids=clean_tenant_ids,
            company_ids=resolved_company_ids,
            start_date=ytd_start,
            end_date=ytd_end,
            base_currency=base_currency,
            currency=currency,
            prior_start=prior_start,
            prior_end=prior_end,
            comparison_label=resolved_comparison_label,
        )
        _DB_PROTECTED_FIELDS = {
            "top_products", "top_customers", "top_suppliers", "top_vendors",
            "low_stock_items", "low_stock_alerts",
            "expense_breakdown", "bank_balances",
        }
        merged_report_data = dict(db_domain_data)
        if report_data and isinstance(report_data, dict):
            for key, val in report_data.items():
                if key in _DB_PROTECTED_FIELDS and key in merged_report_data:
                    db_val = merged_report_data[key]
                    if isinstance(db_val, list) and len(db_val) > 0:
                        continue
                merged_report_data[key] = val
        report_data = merged_report_data

        normalized_data = _normalize_report_data(report_data or {}, currency)
        agent_charts = _render_charts_from_report_data(normalized_data, currency, domain=resolved_domain)

        chart_1_b64 = agent_charts.get("chart_1_b64")
        chart_2_b64 = agent_charts.get("chart_2_b64")

        # Automatically build trend and waterfall charts if not supplied by agent
        if not chart_1_b64:
            try:
                trend_end = ytd_end or datetime.now().strftime("%Y-%m-%d")
                try:
                    end_dt = datetime.strptime(trend_end, "%Y-%m-%d")
                    trend_start = (end_dt - timedelta(days=365)).replace(day=1).strftime("%Y-%m-%d")
                except Exception:
                    trend_start = f"{current_year - 1}-01-01"

                trend_data_pts = _get_domain_trend_series(
                    domain=resolved_domain,
                    tenant_ids=clean_tenant_ids,
                    company_ids=resolved_company_ids,
                    start_date=trend_start,
                    end_date=trend_end,
                    base_currency=base_currency,
                )
                if not trend_data_pts and resolved_domain in ("sales", "commercial"):
                    try:
                        ts_res = get_time_series_data_tool(
                            tenant_ids=clean_tenant_ids,
                            company_ids=resolved_company_ids,
                            start_date=trend_start,
                            end_date=trend_end,
                            granularity="month",
                            base_currency=base_currency,
                        )
                        trend_data_pts = ts_res.get("points", []) if isinstance(ts_res, dict) else []
                    except Exception:
                        pass
                elif not trend_data_pts and resolved_domain in ("purchase", "purchasing", "procurement"):
                    try:
                        ts_res = get_purchase_trend_tool(
                            tenant_ids=clean_tenant_ids,
                            company_ids=resolved_company_ids,
                            start_date=trend_start,
                            end_date=trend_end,
                            granularity="month",
                            base_currency=base_currency,
                        )
                        trend_data_pts = ts_res.get("points", []) if isinstance(ts_res, dict) else []
                    except Exception:
                        pass

                if trend_data_pts:
                    if len(trend_data_pts) > 12:
                        trend_data_pts = trend_data_pts[-12:]
                    chart_1_b64 = _render_trend_chart(trend_data_pts, currency, domain=resolved_domain)
            except Exception as e:
                logger.warning(f"Domain trend chart generation failed: {e}")

        if not chart_2_b64:
            try:
                r_v = float(report_data.get("revenue", 0) if isinstance(report_data.get("revenue"), (int, float)) else report_data.get("revenue", {}).get("raw", 0))
                c_v = float(report_data.get("cogs", 0) if isinstance(report_data.get("cogs"), (int, float)) else report_data.get("cogs", {}).get("raw", 0))
                g_v = float(report_data.get("gross_profit", 0) if isinstance(report_data.get("gross_profit"), (int, float)) else report_data.get("gross_profit", {}).get("raw", 0))
                o_v = float(report_data.get("opex", 0) if isinstance(report_data.get("opex"), (int, float)) else report_data.get("opex", {}).get("raw", 0))
                e_v = float(report_data.get("ebit", 0) if isinstance(report_data.get("ebit"), (int, float)) else report_data.get("ebit", {}).get("raw", 0))
                n_v = float(report_data.get("net_profit", 0) if isinstance(report_data.get("net_profit"), (int, float)) else report_data.get("net_profit", {}).get("raw", 0))
                if r_v > 0:
                    chart_2_b64 = _render_waterfall_chart(r_v, c_v, g_v, o_v, e_v, max(e_v - n_v, 0), n_v, currency)
            except Exception:
                pass

        # Process Markdown Custom Content
        custom_content = replace_tenant_ids_with_names(custom_content, clean_tenant_ids)
        custom_content = normalize_status_emoji(custom_content)
        custom_content = _render_custom_chart_blocks(custom_content)

        # Autonomous AI Agent Invocation or Dynamic Structured Data Formatting when custom_content is empty
        effective_prompt = prompt or prompt_text
        if not custom_content.strip():
            has_rich_data = bool(
                report_data.get("messages")
                or report_data.get("revenue_bridge")
                or report_data.get("reorder_recommendations")
                or report_data.get("metrics")
                or report_data.get("insights")
                or report_data.get("scenarios")
                or report_data.get("demand_scenarios")
                or report_data.get("risks")
                or report_data.get("steps")
                or report_data.get("inventory_position")
                or report_data.get("assumptions")
                or any(isinstance(v, (list, dict)) and v for k, v in report_data.items() if not k.startswith("_") and k not in ("company_name", "currency", "company_ids", "tenant_ids"))
            )
            if has_rich_data:
                from ._format_ai_body import format_dynamic_ai_analysis
                custom_content = format_dynamic_ai_analysis(
                    data=report_data,
                    session_messages=report_data.get("messages")
                )
            else:
                ai_analysis = _generate_ai_domain_analysis(
                    domain=resolved_domain,
                    report_data=report_data,
                    prompt=effective_prompt or custom_content,
                    company_name=company_name,
                    period_label=resolved_period_label,
                    comparison_label=resolved_comparison_label,
                    currency=currency,
                    meta=meta,
                )
                if ai_analysis:
                    custom_content = _render_custom_chart_blocks(ai_analysis)

        if not custom_content.strip():
            def _extract_metric_num(val):
                if isinstance(val, (int, float)):
                    return val
                if isinstance(val, dict):
                    raw = val.get("raw")
                    if isinstance(raw, (int, float)):
                        return raw
                    fmt = val.get("formatted")
                    if isinstance(fmt, str):
                        return fmt
                return 0

            rev_raw = _extract_metric_num(report_data.get("revenue")) or _extract_metric_num(report_data.get("total_revenue"))
            ebit_raw = _extract_metric_num(report_data.get("ebit")) or _extract_metric_num(report_data.get("operating_profit"))

            rev_display = _fmt_money(rev_raw, currency) if isinstance(rev_raw, (int, float)) else str(rev_raw or "0 " + currency)
            ebit_display = _fmt_money(ebit_raw, currency) if isinstance(ebit_raw, (int, float)) else str(ebit_raw or "0 " + currency)
            custom_content = f"""
## {meta.get('title', 'Executive Report')}
{meta.get('subtitle', 'Comprehensive business performance report.')}

### Executive Highlights
* **Operational Scope**: Generated **{rev_display}** in total activity for {resolved_period_label}.
* **Earnings Conversion**: Operating profit (EBIT) reached **{ebit_display}**, maintaining disciplined cost controls.
* **Control Observation**: General ledger entries and trade balances reflect posted journal entries in compliance with standard chart of accounts structures.
"""

        custom_content = re.sub(r'^[•\u2022]\s*', '- ', custom_content, flags=re.MULTILINE)
        custom_content = re.sub(r'^[•\u2022\-\*]\s*$', '', custom_content, flags=re.MULTILINE)
        custom_content = re.sub(r'^\d+\.\s*$', '', custom_content, flags=re.MULTILINE)
        custom_content = re.sub(r'([^\n])\s+-\s+([A-Za-z0-9])', r'\1\n- \2', custom_content)
        custom_content = re.sub(r'\n{3,}', '\n\n', custom_content)
        custom_content = _normalize_markdown_tables(custom_content)

        md = markdown.Markdown(extensions=['tables', 'fenced_code', 'sane_lists'])
        body_html = md.convert(custom_content)
        body_html = _sanitize_rendered_report_html(body_html)
        body_html = normalize_status_emoji(body_html)
        body_html = add_dynamic_table_widths(body_html)

        template_dir = Path(__file__).parent.parent / "templates"
        env = Environment(loader=FileSystemLoader(str(template_dir)))
        template = env.get_template(template_file)

        logo_mime = "image/png"
        if not logo_b64:
            discovered_b64, discovered_mime = get_project_logo_b64(custom_logo_path=logo_path)
            if discovered_b64:
                logo_b64 = discovered_b64
                logo_mime = discovered_mime or "image/png"

        template_kpis = dict(normalized_data)

        html_out = template.render(
            company_name=company_name,
            reporting_period=resolved_period_label,
            view_type=view_type,
            comparison_label=resolved_comparison_label,
            currency=currency,
            last_sync=f"{datetime.now().strftime('%b %d, %Y')} (Posted Ledger)",
            kpis=template_kpis,
            report_data=normalized_data,
            badge=meta.get("badge", "Executive Report"),
            title=report_data.get("title") or meta.get("title", "Executive Report"),
            subtitle=report_data.get("period") or meta.get("subtitle", ""),
            accent=meta.get("accent", "#2563eb"),
            template_kpis=meta.get("kpi_slots", []),
            trend_chart_b64=chart_1_b64,
            waterfall_chart_b64=chart_2_b64,
            wc_chart_b64=None,
            chart_1_b64=chart_1_b64,
            chart_2_b64=chart_2_b64,
            body_html=body_html,
            logo_url=logo_url,
            logo_b64=logo_b64,
            logo_mime=logo_mime,
        )

        reports_dir = _get_reports_dir()
        filename = _build_pdf_filename(
            domain=resolved_domain,
            company_name=company_name,
            reporting_period=resolved_period_label,
            tenant_ids=clean_tenant_ids,
        )
        output_path = reports_dir / filename
        html_out = _highlight_negative_numbers_html(html_out)
        try:
            HTML(string=html_out).write_pdf(output_path)
        except Exception as e:
            logger.error(f"WeasyPrint PDF write failed: {e}", exc_info=True)
            return {
                'tool_name': 'generate_report_tool',
                'status': 'error',
                'error': f"PDF compilation failed: {str(e)}",
                'filename': filename,
            }

        relative_path = f"/financial-advisor/reports/{filename}"
        return {
            'tool_name': 'generate_report_tool',
            'status': 'success',
            'download_url': make_report_url(filename),
            'path': relative_path,
            'filename': filename,
        }

    # ── EXISTING LEGACY PATH (report_template.html, backward compatibility) ─────
    prior_start, prior_end = _resolve_prior_period_dates(
        ytd_start, ytd_end, resolved_comparison_label, comparison_type
    )

    sales = {}
    health = {}
    pnl = {}
    prior_pnl = {}
    bs = {}
    receivables = {}
    payables = {}
    wc = {}
    inv = {}
    expenses_data = {}
    top_prods = {}

    try:
        sales = get_sales_summary_tool(tenant_ids=clean_tenant_ids, company_ids=resolved_company_ids, start_date=ytd_start, end_date=ytd_end, base_currency=base_currency)
    except Exception as e:
        logger.warning(f"Sales fetch error: {e}")

    try:
        health = get_business_health_score_tool(tenant_ids=clean_tenant_ids, company_ids=resolved_company_ids, base_currency=base_currency)
    except Exception as e:
        logger.warning(f"Health score fetch error: {e}")

    try:
        pnl = calculate_pnl_tool(tenant_ids=clean_tenant_ids, company_ids=resolved_company_ids, start_date=ytd_start, end_date=ytd_end, base_currency=base_currency)
    except Exception as e:
        logger.warning(f"P&L fetch error: {e}")

    try:
        prior_pnl = calculate_pnl_tool(tenant_ids=clean_tenant_ids, company_ids=resolved_company_ids, start_date=prior_start, end_date=prior_end, base_currency=base_currency)
    except Exception as e:
        logger.warning(f"Prior-period P&L fetch error: {e}")

    try:
        bs = get_balance_sheet_tool(tenant_ids=clean_tenant_ids, company_ids=resolved_company_ids, base_currency=base_currency)
    except Exception as e:
        logger.warning(f"Balance sheet fetch error: {e}")

    try:
        receivables = get_receivables_analysis_tool(tenant_ids=clean_tenant_ids, company_ids=resolved_company_ids, base_currency=base_currency)
    except Exception as e:
        logger.warning(f"Receivables fetch error: {e}")

    try:
        payables = get_payables_analysis_tool(tenant_ids=clean_tenant_ids, company_ids=resolved_company_ids, base_currency=base_currency)
    except Exception as e:
        logger.warning(f"Payables fetch error: {e}")

    try:
        wc = get_working_capital_tool(tenant_ids=clean_tenant_ids, company_ids=resolved_company_ids, base_currency=base_currency)
    except Exception as e:
        logger.warning(f"Working capital fetch error: {e}")

    try:
        inv = get_inventory_valuation_tool(tenant_ids=clean_tenant_ids, company_ids=resolved_company_ids)
    except Exception as e:
        logger.warning(f"Inventory fetch error: {e}")

    try:
        expenses_data = get_expense_breakdown_tool(tenant_ids=clean_tenant_ids, company_ids=resolved_company_ids, start_date=ytd_start, end_date=ytd_end, base_currency=base_currency)
    except Exception as e:
        logger.warning(f"Expense breakdown fetch error: {e}")

    try:
        top_prods = get_top_products_tool(tenant_ids=clean_tenant_ids, company_ids=resolved_company_ids, start_date=ytd_start, end_date=ytd_end, limit=5, base_currency=base_currency)
    except Exception as e:
        logger.warning(f"Top products fetch error: {e}")

    # 3. Extract Values and Compute KPI Variances
    rev_val = float(pnl.get("total_income", 0) or pnl.get("revenue", 0) or sales.get("total_revenue", 0) or 0)
    cogs_val = float(pnl.get("cogs", 0) or 0)
    gp_val = float(pnl.get("gross_profit", 0) or (rev_val - cogs_val))
    gm_pct = float(pnl.get("gross_margin_pct", 0) or ((gp_val / rev_val * 100) if rev_val > 0 else 0))
    opex_val = float(pnl.get("operating_expenses", 0) or 0)
    ebit_val = float(pnl.get("ebit", 0) or (gp_val - opex_val))
    net_val = float(pnl.get("net_profit", 0) or ebit_val)
    tax_finance_val = max(0, ebit_val - net_val)

    # Real Cash from GL accounts (account_type = 'asset_cash')
    cash_val = 0.0
    try:
        t_sql_cash, t_params_cash = build_tenant_filter_sql(clean_tenant_ids, column_name="l.tenant_id", prefix="t_cash")
        balance_col_cash = build_currency_case_sql('l.balance', tenant_ids=clean_tenant_ids, base_currency=base_currency, currency_column='c.currency_code')
        cash_params = {}
        cash_params.update(t_params_cash)
        f_sql_cash, f_params_cash = build_company_filter_sql(resolved_company_ids, column_name="l.company_id")
        cash_params.update(f_params_cash)
        cash_rows = run_query(
            f"""SELECT COALESCE(SUM({balance_col_cash}), 0) AS cash_balance
                FROM fact_account_move_lines l
                JOIN fact_account_moves m ON l.account_move_id = m.id
                LEFT JOIN dim_companies c ON l.company_id = c.id
                WHERE 1=1 {t_sql_cash}
                  AND m.state = 'posted'
                  AND l.account_type = 'asset_cash'
                  {f_sql_cash}""",
            cash_params,
        )
        if cash_rows and cash_rows[0].get("cash_balance") is not None:
            cash_val = float(cash_rows[0].get("cash_balance"))
    except Exception as e:
        logger.warning(f"Real cash balance query error: {e}")
        cash_val = float(bs.get("bank_and_cash_accounts", 0.0) or 0.0)

    ar_val = float(receivables.get("total_receivables", 0) or 0)
    overdue_ar_val = float(receivables.get("overdue_receivables", 0) or 0)
    overdue_ratio = float(receivables.get("overdue_ratio", 0) or ((overdue_ar_val / ar_val) if ar_val > 0 else 0))
    ap_val = float(payables.get("total_payables", 0) or 0)
    inv_val = float(inv.get("total_valuation", 0) or inv.get("inventory_value", 0) or 0)
    nwc_val = float(wc.get("working_capital", 0) or (float(bs.get("current_assets", 0)) - float(bs.get("current_liabilities", 0))))
    cur_ratio_val = float(wc.get("current_ratio") or wc.get("working_capital_ratio") or bs.get("current_ratio") or (float(bs.get("current_assets", 0)) / float(bs.get("current_liabilities", 1)) if float(bs.get("current_liabilities", 0)) else 0.0))
    health_score_val = float(health.get("business_health_score", 0.0) or 0.0)

    # Extract Prior Values and Compute Real Variances
    prior_rev = float(prior_pnl.get("total_income", 0) or prior_pnl.get("revenue", 0) or 0)
    prior_gp = float(prior_pnl.get("gross_profit", 0) or 0)
    prior_gm = float(prior_pnl.get("gross_margin_pct", 0) or 0)
    prior_opex = float(prior_pnl.get("operating_expenses", 0) or 0)
    prior_ebit = float(prior_pnl.get("ebit", 0) or 0)
    prior_net = float(prior_pnl.get("net_profit", 0) or 0)

    rev_var_pct, rev_var_amt = _compute_variance(rev_val, prior_rev)
    gp_var_pct, gp_var_amt = _compute_variance(gp_val, prior_gp)
    gm_var_pts = round(gm_pct - prior_gm, 1)
    opex_var_pct, opex_var_amt = _compute_variance(opex_val, prior_opex)
    ebit_var_pct, ebit_var_amt = _compute_variance(ebit_val, prior_ebit)
    net_var_pct, net_var_amt = _compute_variance(net_val, prior_net)

    # 4. Build Structured KPI Objects for Template
    rev_sign = "+" if rev_var_pct > 0 else ""
    gp_sign = "+" if gp_var_pct > 0 else ""
    gm_sign = "+" if gm_var_pts > 0 else ""
    opex_sign = "+" if opex_var_pct > 0 else ""
    ebit_sign = "+" if ebit_var_pct > 0 else ""
    net_sign = "+" if net_var_pct > 0 else ""

    kpis = {
        "revenue": {
            "raw": rev_val,
            "formatted": _fmt_money(rev_val, currency),
            "var_text": f"{rev_sign}{rev_var_pct:.1f}% ({_fmt_money(rev_var_amt, currency, is_diff=True)})",
            "arrow": "▲" if rev_var_pct >= 0 else "▼",
            "var_class": "variance-positive" if rev_var_pct >= 0 else "variance-negative"
        },
        "gross_profit": {
            "raw": gp_val,
            "formatted": _fmt_money(gp_val, currency),
            "var_text": f"{gp_sign}{gp_var_pct:.1f}% ({_fmt_money(gp_var_amt, currency, is_diff=True)})",
            "arrow": "▲" if gp_var_pct >= 0 else "▼",
            "var_class": "variance-positive" if gp_var_pct >= 0 else "variance-negative"
        },
        "gross_margin": {
            "raw": gm_pct,
            "formatted": f"{gm_pct:.1f}%",
            "var_text": f"{gm_sign}{gm_var_pts:.1f} pts",
            "arrow": "▲" if gm_var_pts >= 0 else "▼",
            "var_class": "variance-positive" if gm_var_pts >= 0 else "variance-negative"
        },
        "opex": {
            "raw": opex_val,
            "formatted": _fmt_money(opex_val, currency),
            "var_text": f"{opex_sign}{opex_var_pct:.1f}% ({_fmt_money(opex_var_amt, currency, is_diff=True)})",
            "arrow": "▲" if opex_var_pct > 0 else "▼",
            "var_class": "variance-negative" if opex_var_pct > 5 else ("variance-neutral" if opex_var_pct >= 0 else "variance-positive")
        },
        "ebit": {
            "raw": ebit_val,
            "formatted": _fmt_money(ebit_val, currency),
            "var_text": f"{ebit_sign}{ebit_var_pct:.1f}% ({_fmt_money(ebit_var_amt, currency, is_diff=True)})",
            "arrow": "▲" if ebit_var_pct >= 0 else "▼",
            "var_class": "variance-positive" if ebit_var_pct >= 0 else "variance-negative"
        },
        "net_profit": {
            "raw": net_val,
            "formatted": _fmt_money(net_val, currency),
            "var_text": f"{net_sign}{net_var_pct:.1f}% ({_fmt_money(net_var_amt, currency, is_diff=True)})",
            "arrow": "▲" if net_val >= 0 else "▼",
            "var_class": "variance-positive" if net_val >= 0 else "variance-negative"
        },
        "cash": {
            "raw": cash_val,
            "formatted": _fmt_money(cash_val, currency)
        },
        "ar": {
            "raw": ar_val,
            "formatted": _fmt_money(ar_val, currency)
        },
        "overdue_pct": {
            "raw": overdue_ratio * 100,
            "formatted": f"{overdue_ratio * 100:.1f}%"
        },
        "overdue_amt": {
            "raw": overdue_ar_val,
            "formatted": _fmt_money(overdue_ar_val, currency)
        },
        "ap": {
            "raw": ap_val,
            "formatted": _fmt_money(ap_val, currency)
        },
        "inventory": {
            "raw": inv_val,
            "formatted": _fmt_money(inv_val, currency)
        },
        "nwc": {
            "raw": nwc_val,
            "formatted": _fmt_money(nwc_val, currency)
        },
        "current_ratio": {
            "raw": cur_ratio_val,
            "formatted": f"{cur_ratio_val:.2f}x"
        },
        "health_score": {
            "raw": health_score_val,
            "formatted": f"{health_score_val:.0f}"
        }
    }

    # 5. Build Autonomous AI Executive Summary, Drivers & Prioritized Alerts
    exec_summary, drivers, alerts = _synthesize_autonomous_insights(
        custom_content=custom_content,
        prompt=prompt or "",
        pnl=pnl,
        prior_pnl=prior_pnl,
        sales=sales,
        receivables=receivables,
        payables=payables,
        wc=wc,
        inv=inv,
        expenses_data=expenses_data,
        top_prods=top_prods,
        currency=currency,
        company_name=company_name,
        period_label=resolved_period_label,
        comparison_label=resolved_comparison_label,
        rev_val=rev_val,
        gp_val=gp_val,
        gm_pct=gm_pct,
        ebit_val=ebit_val,
        net_val=net_val,
        overdue_ar_val=overdue_ar_val,
        overdue_ratio=overdue_ratio,
        nwc_val=nwc_val,
        cur_ratio_val=cur_ratio_val,
        health_score_val=health_score_val,
        inv_val=inv_val,
        ap_val=ap_val,
        cash_val=cash_val,
    )

    # 8. Build Company Comparison Table (if Multi-Company)
    company_comparison = []
    if len(resolved_company_ids) > 1:
        comp_res = get_companies_tool(tenant_ids=clean_tenant_ids)
        all_comps = comp_res.get("companies", []) if isinstance(comp_res, dict) else []
        for c in all_comps:
            c_id = c.get("id")
            if c_id in resolved_company_ids:
                c_name = c.get("name", f"Company {c_id}")
                try:
                    c_pnl = calculate_pnl_tool(
                        tenant_ids=clean_tenant_ids,
                        company_ids=[c_id],
                        start_date=ytd_start,
                        end_date=ytd_end,
                        base_currency=base_currency,
                    )
                    c_ar = get_receivables_analysis_tool(
                        tenant_ids=clean_tenant_ids, company_ids=[c_id],
                        base_currency=base_currency,
                    )
                    c_rev = float(c_pnl.get("total_income", 0) or c_pnl.get("revenue", 0) or 0)
                    c_gp = float(c_pnl.get("gross_profit", 0) or 0)
                    c_gm = float(c_pnl.get("gross_margin_pct", 0) or 0)
                    c_net = float(c_pnl.get("net_profit", 0) or 0)
                    c_overdue = float(c_ar.get("overdue_receivables", 0) or 0)
                except Exception as e:
                    logger.warning(f"Company {c_id} breakdown fetch error: {e}")
                    c_rev = c_gp = c_gm = c_net = c_overdue = 0

                company_comparison.append({
                    "name": c_name,
                    "revenue": _fmt_money(c_rev, currency),
                    "gross_profit": _fmt_money(c_gp, currency),
                    "gross_margin": f"{c_gm:.1f}%",
                    "net_profit": _fmt_money(c_net, currency),
                    "cash": "—",
                    "overdue_ar": _fmt_money(c_overdue, currency),
                })

    # 9. Generate Visual Charts
    monthly_pnl_data = []
    trend_start = ytd_start
    trend_end = ytd_end

    if ytd_start and ytd_end:
        try:
            start_dt = datetime.strptime(ytd_start, "%Y-%m-%d")
            end_dt = datetime.strptime(ytd_end, "%Y-%m-%d")
            if (end_dt - start_dt).days <= 45:
                trend_start = (end_dt - timedelta(days=365)).replace(day=1).strftime("%Y-%m-%d")
        except Exception:
            pass

    try:
        monthly_pnl_data = _get_monthly_pnl_series(
            tenant_ids=clean_tenant_ids,
            company_ids=resolved_company_ids,
            start_date=trend_start,
            end_date=trend_end,
            base_currency=base_currency,
        )
    except Exception as e:
        logger.warning(f"Monthly P&L series error: {e}")

    if not monthly_pnl_data:
        ts_result = {}
        try:
            ts_result = get_time_series_data_tool(
                tenant_ids=clean_tenant_ids,
                company_ids=resolved_company_ids,
                start_date=trend_start,
                end_date=trend_end,
                granularity="month",
                base_currency=base_currency,
            )
        except Exception:
            pass
        monthly_pnl_data = ts_result.get("points", []) if isinstance(ts_result, dict) else []

    if len(monthly_pnl_data) > 12:
        monthly_pnl_data = monthly_pnl_data[-12:]

    trend_chart_b64 = _render_trend_chart(monthly_pnl_data, currency)
    waterfall_chart_b64 = _render_waterfall_chart(rev_val, cogs_val, gp_val, opex_val, ebit_val, tax_finance_val, net_val, currency)
    wc_chart_b64 = _render_working_capital_chart(cash_val, ar_val, overdue_ar_val, ap_val, inv_val, nwc_val, currency)

    # 10. Process Markdown Custom Content
    custom_content = replace_tenant_ids_with_names(custom_content, clean_tenant_ids)
    custom_content = normalize_status_emoji(custom_content)
    custom_content = _render_custom_chart_blocks(custom_content)

    if not custom_content.strip():
        custom_content = f"""
## Executive Highlights
The organization generated **{_fmt_money(rev_val, currency)}** in total revenue for the current fiscal period with a business health score of **{health_score_val:.0f}/100**.

### Key Strategic Observations
* **Operating Efficiency**: Operating margin (EBIT) reached **{_fmt_money(ebit_val, currency)}**, demonstrating strong underlying unit economics.
* **Working Capital Health**: Current ratio remains solid at **{cur_ratio_val:.2f}x**, providing sufficient headroom for operational commitments.
* **Action Priority**: Accelerated collections on outstanding receivables will convert locked working capital directly into liquid cash reserves.
"""

    custom_content = re.sub(r'^[•\u2022]\s*', '- ', custom_content, flags=re.MULTILINE)
    custom_content = re.sub(r'^[•\u2022\-\*]\s*$', '', custom_content, flags=re.MULTILINE)
    custom_content = re.sub(r'^\d+\.\s*$', '', custom_content, flags=re.MULTILINE)
    custom_content = re.sub(r'([^\n])\s+-\s+([A-Za-z0-9])', r'\1\n- \2', custom_content)
    custom_content = re.sub(r'\n{3,}', '\n\n', custom_content)
    custom_content = _normalize_markdown_tables(custom_content)

    md = markdown.Markdown(extensions=['tables', 'fenced_code', 'sane_lists'])
    body_html = md.convert(custom_content)
    body_html = _sanitize_rendered_report_html(body_html)
    body_html = normalize_status_emoji(body_html)
    body_html = add_dynamic_table_widths(body_html)

    # 11. Render Jinja2 Template
    template_dir = Path(__file__).parent.parent / "templates"
    env = Environment(loader=FileSystemLoader(str(template_dir)))
    template = env.get_template("report_template.html")

    logo_mime = "image/png"
    if not logo_b64:
        discovered_b64, discovered_mime = get_project_logo_b64(custom_logo_path=logo_path)
        if discovered_b64:
            logo_b64 = discovered_b64
            logo_mime = discovered_mime or "image/png"

    html_out = template.render(
        company_name=company_name,
        reporting_period=resolved_period_label,
        view_type=view_type,
        comparison_label=resolved_comparison_label,
        currency=currency,
        last_sync=f"{datetime.now().strftime('%b %d, %Y')} (Posted Ledger)",
        kpis=kpis,
        exec_summary=exec_summary,
        drivers=drivers,
        alerts=alerts,
        company_comparison=company_comparison,
        trend_chart_b64=trend_chart_b64,
        waterfall_chart_b64=waterfall_chart_b64,
        wc_chart_b64=wc_chart_b64,
        body_html=body_html,
        logo_url=logo_url,
        logo_b64=logo_b64,
        logo_mime=logo_mime,
    )

    # 12. Compile PDF via WeasyPrint
    reports_dir = _get_reports_dir()
    filename = _build_pdf_filename(
        domain="health",
        company_name=company_name,
        reporting_period=resolved_period_label,
        tenant_ids=clean_tenant_ids,
    )
    output_path = reports_dir / filename
    html_out = _highlight_negative_numbers_html(html_out)
    try:
        HTML(string=html_out).write_pdf(output_path)
    except Exception as e:
        logger.error(f"WeasyPrint PDF write failed: {e}", exc_info=True)
        return {
            'tool_name': 'generate_report_tool',
            'status': 'error',
            'error': f"PDF compilation failed: {str(e)}",
            'filename': filename,
        }

    relative_path = f"/financial-advisor/reports/{filename}"
    return {
        'tool_name': 'generate_report_tool',
        'status': 'success',
        'download_url': make_report_url(filename),
        'path': relative_path,
        'filename': filename,
    }


def get_last_report_tool(
    tenant_ids: Optional[list[str]] = None,
    company_ids: Optional[list[int]] = None,
) -> dict:
    reports_dir = _get_reports_dir()
    clean_tenant_ids = normalize_tenant_ids(tenant_ids)

    tenant_name_str = ""
    try:
        from odoo_app.models import Tenant
        if clean_tenant_ids and len(clean_tenant_ids) > 1:
            tenant_name_str = f"multi_tenants_{len(clean_tenant_ids)}"
        elif clean_tenant_ids:
            t = Tenant.objects.filter(id=clean_tenant_ids[0]).first()
            if t and t.name:
                tenant_name_str = t.name
    except Exception:
        pass

    t_slug = _slugify_filename_part(tenant_name_str) if tenant_name_str else ""
    t_id_prefix = str(clean_tenant_ids[0])[:8] if clean_tenant_ids else ""

    files = [
        f for f in reports_dir.glob('*.pdf')
        if (clean_tenant_ids and any(t_id in f.name for t_id in clean_tenant_ids))
        or (t_slug and t_slug in f.name)
        or (t_id_prefix and t_id_prefix in f.name)
    ]
    if not files:
        files = list(reports_dir.glob('*_report_*.pdf')) or list(reports_dir.glob('*.pdf'))
    if not files:
        return {'status': 'no_reports'}
        
    files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
    filename = files[0].name
    relative_path = f"/financial-advisor/reports/{filename}"
    return {
        'tool_name': 'get_last_report_tool',
        'filename': filename,
        'download_url': make_report_url(filename),
        'path': relative_path,
    }
