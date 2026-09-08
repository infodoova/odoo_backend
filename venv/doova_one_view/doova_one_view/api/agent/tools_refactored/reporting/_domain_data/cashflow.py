# doova_one_view/api/agent/tools_refactored/reporting/_domain_data/cashflow.py

import logging
from typing import Optional, List, Dict, Any

from .._formatters import _fmt_money
from .._variance import _build_kpi_variance

logger = logging.getLogger(__name__)


def enrich(
    data: dict,
    pnl_ctx: dict,
    tenant_ids: list[str] | None = None,
    company_ids: list[int] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    base_currency: str | None = None,
    currency: str = "XAF",
    prior_start: str | None = None,
    prior_end: str | None = None,
    comparison_label: str = "",
) -> None:
    """Enriches data dict with Cash Flow & Liquidity telemetry matching Odoo Enterprise Cash Flow Statement."""
    from doova_one_view.api.agent.query_context import normalize_tenant_ids, normalize_company_ids
    tenant_ids = normalize_tenant_ids(tenant_ids)
    company_ids = normalize_company_ids(company_ids)

    from doova_one_view.api.agent.tools_refactored import reporting_v2
    get_balance_sheet_tool = getattr(reporting_v2, "get_balance_sheet_tool", None)
    get_cash_flow_statement_tool = getattr(reporting_v2, "get_cash_flow_statement_tool", None)

    if not get_balance_sheet_tool:
        from doova_one_view.api.agent.tools_refactored.finance import get_balance_sheet_tool
    if not get_cash_flow_statement_tool:
        from doova_one_view.api.agent.tools_refactored.finance_v2 import get_cash_flow_statement_tool

    try:
        cf = get_cash_flow_statement_tool(tenant_ids=tenant_ids, company_ids=company_ids, start_date=start_date, end_date=end_date, base_currency=base_currency)
        bs = get_balance_sheet_tool(tenant_ids=tenant_ids, company_ids=company_ids, as_of_date=end_date, base_currency=base_currency)
        
        prior_cf = {}
        if prior_start and prior_end:
            try:
                prior_cf = get_cash_flow_statement_tool(tenant_ids=tenant_ids, company_ids=company_ids, start_date=prior_start, end_date=prior_end, base_currency=base_currency)
            except Exception:
                pass

        op_dict = cf.get("operating_activities", {})
        inv_dict = cf.get("investing_activities", {})
        fin_dict = cf.get("financing_activities", {})
        unclass_dict = cf.get("unclassified_activities", {})

        op_val = float(cf.get("net_cash_from_operating", 0) or op_dict.get("total", 0) or 0)
        inv_val = float(cf.get("net_cash_from_investing", 0) or inv_dict.get("total", 0) or 0)
        fin_val = float(cf.get("net_cash_from_financing", 0) or fin_dict.get("total", 0) or 0)
        unclass_val = float(cf.get("net_cash_from_unclassified", 0) or unclass_dict.get("total", 0) or 0)
        net_mov = float(cf.get("net_change_in_cash", 0) or cf.get("net_increase", 0) or (op_val + inv_val + fin_val + unclass_val) or 0)
        beg_bal = float(cf.get("beginning_balance", 0) or 0)
        end_bal = float(cf.get("closing_balance", 0.0))
        cash_val = end_bal

        cust_adv = float(op_dict.get("customer_advances", op_dict.get("customer_payments", 0.0)) or 0.0)
        supp_adv = float(op_dict.get("supplier_advances", op_dict.get("supplier_payments", 0.0)) or 0.0)
        direct_rec = float(op_dict.get("cash_received_from_operating_activities", op_dict.get("direct_receipts", 0.0)) or 0.0)
        direct_paid = float(op_dict.get("cash_paid_for_operating_activities", op_dict.get("direct_payments", 0.0)) or 0.0)

        inv_in = float(inv_dict.get("cash_in", 0.0) or 0.0)
        inv_out = float(inv_dict.get("cash_out", 0.0) or 0.0)
        fin_in = float(fin_dict.get("cash_in", 0.0) or 0.0)
        fin_out = float(fin_dict.get("cash_out", 0.0) or 0.0)
        unclass_in = float(unclass_dict.get("cash_in", 0.0) or 0.0)
        unclass_out = float(unclass_dict.get("cash_out", 0.0) or 0.0)

        prior_op_val = float(prior_cf.get("net_cash_from_operating", 0) or prior_cf.get("operating_activities", {}).get("total", 0) or 0)
        prior_inv_val = float(prior_cf.get("net_cash_from_investing", 0) or prior_cf.get("investing_activities", {}).get("total", 0) or 0)
        prior_fin_val = float(prior_cf.get("net_cash_from_financing", 0) or prior_cf.get("financing_activities", {}).get("total", 0) or 0)
        prior_net_mov = float(prior_cf.get("net_change_in_cash", 0) or prior_cf.get("net_increase", 0) or (prior_op_val + prior_inv_val + prior_fin_val) or 0)

        # Cash Runway Calculation based on monthly operating burn
        opex_f = pnl_ctx.get("opex_f", 0.0)
        monthly_burn = max(0.0, opex_f / 8.0) if opex_f > 0 else 0.0
        if cash_val > 0 and monthly_burn > 0:
            runway_val = cash_val / monthly_burn
            runway_str = f"{runway_val:.1f} Mos"
        elif cash_val <= 0:
            runway_val = 0.0
            runway_str = "0.0 Mos (Overdrawn)"
        else:
            runway_val = 12.0
            runway_str = "12.0+ Mos"

        # Query real granular bank & cash accounts matching Cash Flow liquidity definition
        from doova_one_view.api.accounting.cash_flow_engine import CashFlowEngine
        from odoo_app.models import AccountMoveLine
        liq_filter = CashFlowEngine.get_liquidity_filter(tenant_ids=tenant_ids)
        end_date_str = end_date or "2099-12-31"

        liq_qs = AccountMoveLine.objects.filter(
            liq_filter,
            account_move__state="posted",
            account_move__date__lte=end_date_str
        )
        if tenant_ids:
            if len(tenant_ids) == 1:
                liq_qs = liq_qs.filter(tenant_id=tenant_ids[0])
            else:
                liq_qs = liq_qs.filter(tenant_id__in=tenant_ids)
        if company_ids:
            if len(company_ids) == 1:
                liq_qs = liq_qs.filter(company_id=company_ids[0])
            else:
                liq_qs = liq_qs.filter(company_id__in=company_ids)

        from django.db.models import Sum
        acct_aggs = liq_qs.values("account_code", "account_name", "company__currency_code").annotate(
            ending_balance=Sum("balance")
        ).order_by("ending_balance")

        bank_accounts_list = []
        for r in acct_aggs:
            b_bal = float(r.get("ending_balance") or 0)
            if abs(b_bal) < 0.01:
                continue
            b_name = r.get("account_name") or "Cash / Bank Account"
            b_code = r.get("account_code")
            display_name = f"{b_code} - {b_name}" if b_code and b_code not in b_name else b_name
            bank_accounts_list.append({
                "account_name": display_name,
                "name": display_name,
                "currency": r.get("company__currency_code") or currency,
                "balance": _fmt_money(b_bal, currency),
                "raw_balance": b_bal,
                "status": "Active" if b_bal >= 0 else "Overdrawn",
            })

        if not bank_accounts_list:
            bank_accounts_list = [
                {
                    "account_name": "General Operating & Bank Accounts",
                    "name": "General Operating & Bank Accounts",
                    "currency": currency,
                    "balance": _fmt_money(cash_val, currency),
                    "status": "Active" if cash_val >= 0 else "Overdrawn",
                }
            ]

        # Structured Statement of Cash Flows table matching Odoo layout
        cf_statement_rows = [
            {"name": "Cash and cash equivalents, beginning of period", "is_bold": True, "amount": _fmt_money(beg_bal, currency)},
            {"name": "Cash flows from operating activities", "is_header": True, "is_bold": True, "amount": _fmt_money(op_val, currency)},
            {"name": "  Advance Payments received from customers", "amount": _fmt_money(cust_adv, currency)},
            {"name": "  Cash received from operating activities", "amount": _fmt_money(direct_rec, currency)},
            {"name": "  Advance payments made to suppliers", "amount": _fmt_money(supp_adv, currency)},
            {"name": "  Cash paid for operating activities", "amount": _fmt_money(direct_paid, currency)},
            {"name": "Cash flows from investing & extraordinary activities", "is_header": True, "is_bold": True, "amount": _fmt_money(inv_val, currency)},
            {"name": "  Cash in", "amount": _fmt_money(inv_in, currency)},
            {"name": "  Cash out", "amount": _fmt_money(inv_out, currency)},
            {"name": "Cash flows from financing activities", "is_header": True, "is_bold": True, "amount": _fmt_money(fin_val, currency)},
            {"name": "  Cash in", "amount": _fmt_money(fin_in, currency)},
            {"name": "  Cash out", "amount": _fmt_money(fin_out, currency)},
            {"name": "Cash flows from unclassified activities", "is_header": True, "is_bold": True, "amount": _fmt_money(unclass_val, currency)},
            {"name": "  Cash in", "amount": _fmt_money(unclass_in, currency)},
            {"name": "  Cash out", "amount": _fmt_money(unclass_out, currency)},
            {"name": "Net increase in cash and cash equivalents", "is_total": True, "is_bold": True, "amount": _fmt_money(net_mov, currency)},
            {"name": "Cash and cash equivalents, closing balance", "is_total": True, "is_bold": True, "amount": _fmt_money(end_bal, currency)},
        ]

        data.update({
            "cash_balance": _build_kpi_variance(end_bal, beg_bal, currency, fmt="money", polarity="positive"),
            "cash": _build_kpi_variance(end_bal, beg_bal, currency, fmt="money", polarity="positive"),
            "cash_and_bank": _build_kpi_variance(end_bal, beg_bal, currency, fmt="money", polarity="positive"),
            "liquid_cash": _build_kpi_variance(end_bal, beg_bal, currency, fmt="money", polarity="positive"),
            "cash_from_operations": _build_kpi_variance(op_val, prior_op_val, currency, fmt="money", polarity="positive"),
            "operating_cash_flow": _build_kpi_variance(op_val, prior_op_val, currency, fmt="money", polarity="positive"),
            "operating_cashflow": _build_kpi_variance(op_val, prior_op_val, currency, fmt="money", polarity="positive"),
            "cash_from_investing": _build_kpi_variance(inv_val, prior_inv_val, currency, fmt="money", polarity="neutral"),
            "investing_cash_flow": _build_kpi_variance(inv_val, prior_inv_val, currency, fmt="money", polarity="neutral"),
            "cash_from_financing": _build_kpi_variance(fin_val, prior_fin_val, currency, fmt="money", polarity="neutral"),
            "financing_cash_flow": _build_kpi_variance(fin_val, prior_fin_val, currency, fmt="money", polarity="neutral"),
            "net_cash_flow": _build_kpi_variance(net_mov, prior_net_mov, currency, fmt="money", polarity="positive"),
            "net_cash_movement": _build_kpi_variance(net_mov, prior_net_mov, currency, fmt="money", polarity="positive"),
            "cash_runway": {"raw": runway_val, "formatted": runway_str},
            "runway": {"raw": runway_val, "formatted": runway_str},
            "bank_balances": bank_accounts_list,
            "cash_flow_statement": cf_statement_rows,
        })
        if prior_op_val != 0 or prior_net_mov != 0:
            if "prior_period" not in data:
                data["prior_period"] = {}
            data["prior_period"].update({
                "operating_cash_flow": prior_op_val,
                "investing_cash_flow": prior_inv_val,
                "financing_cash_flow": prior_fin_val,
                "net_cash_movement": prior_net_mov,
                "beginning_balance": beg_bal,
                "comparison_label": comparison_label,
            })
    except Exception as e:
        logger.warning(f"Cashflow domain query error: {e}")
