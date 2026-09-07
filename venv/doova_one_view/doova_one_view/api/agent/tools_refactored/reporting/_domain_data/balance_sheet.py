# doova_one_view/api/agent/tools_refactored/reporting/_domain_data/balance_sheet.py

import logging
from datetime import datetime
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
    """Enriches data dict with Balance Sheet and Solvency telemetry (comparative balance sheet statement rows)."""
    from doova_one_view.api.agent.tools_refactored import reporting_v2
    get_balance_sheet_tool = reporting_v2.get_balance_sheet_tool
    get_working_capital_tool = reporting_v2.get_working_capital_tool

    try:
        bs = get_balance_sheet_tool(tenant_ids=tenant_ids, company_ids=company_ids, as_of_date=end_date, base_currency=base_currency)
        wc = get_working_capital_tool(tenant_ids=tenant_ids, company_ids=company_ids, base_currency=base_currency)
        
        # Prior Period Balance Sheet for Comparison
        prior_bs = {}
        if prior_end:
            try:
                prior_bs = get_balance_sheet_tool(tenant_ids=tenant_ids, company_ids=company_ids, as_of_date=prior_end, base_currency=base_currency)
            except Exception:
                pass
        elif end_date:
            try:
                end_dt = datetime.strptime(end_date, "%Y-%m-%d")
                prior_as_of = (end_dt.replace(year=end_dt.year - 1)).strftime("%Y-%m-%d")
                prior_bs = get_balance_sheet_tool(tenant_ids=tenant_ids, company_ids=company_ids, as_of_date=prior_as_of, base_currency=base_currency)
            except Exception:
                pass

        total_assets = float(bs.get("total_assets", 0) or 0)
        current_assets = float(bs.get("current_assets", 0) or 0)
        non_current_assets = float(bs.get("non_current_assets", 0) or 0)
        fixed_assets = float(bs.get("fixed_assets", 0) or 0)
        total_liabilities = float(bs.get("total_liabilities", 0) or 0)
        current_liabilities = float(bs.get("current_liabilities", 0) or 0)
        non_current_liabilities = float(bs.get("non_current_liabilities", 0) or 0)
        total_equity = float(bs.get("total_equity", 0) or 0)
        retained_earnings = float(bs.get("retained_earnings", 0) or 0)
        unallocated_earnings = float(bs.get("unallocated_earnings", 0) or 0)
        cash = float(bs.get("bank_and_cash_accounts", 0) or 0)
        receivables = float(bs.get("receivables", 0) or 0)
        prepayments = float(bs.get("prepayments", 0) or 0)
        payables = float(bs.get("payables", 0) or 0)
        cur_ratio = float(bs.get("current_ratio") or wc.get("current_ratio") or (current_assets / current_liabilities if current_liabilities else 0.0))
        nwc_val = float(wc.get("working_capital") or (current_assets - current_liabilities))

        prior_ta = float(prior_bs.get("total_assets", 0) or 0)
        prior_ca = float(prior_bs.get("current_assets", 0) or 0)
        prior_nca = float(prior_bs.get("non_current_assets", 0) or 0)
        prior_fa = float(prior_bs.get("fixed_assets", 0) or 0)
        prior_tl = float(prior_bs.get("total_liabilities", 0) or 0)
        prior_cl = float(prior_bs.get("current_liabilities", 0) or 0)
        prior_ncl = float(prior_bs.get("non_current_liabilities", 0) or 0)
        prior_eq = float(prior_bs.get("total_equity", 0) or 0)
        prior_re = float(prior_bs.get("retained_earnings", 0) or 0)
        prior_ue = float(prior_bs.get("unallocated_earnings", 0) or 0)
        prior_cash = float(prior_bs.get("bank_and_cash_accounts", 0) or 0)
        prior_rec = float(prior_bs.get("receivables", 0) or 0)
        prior_prep = float(prior_bs.get("prepayments", 0) or 0)
        prior_pay = float(prior_bs.get("payables", 0) or 0)
        prior_cr = float(prior_bs.get("current_ratio", 0) or (prior_ca / prior_cl if prior_cl else 0.0))
        prior_nwc = float(prior_ca - prior_cl)

        has_prior = prior_ta > 0 or prior_tl > 0 or prior_eq > 0

        bs_statement = [
            {"name": "ASSETS", "is_header": True, "is_bold": True, "current": "", "prior": ""},
            {"name": "Cash & Cash Equivalents", "current": _fmt_money(cash, currency), "prior": _fmt_money(prior_cash, currency) if has_prior else "—"},
            {"name": "Accounts Receivable", "current": _fmt_money(receivables, currency), "prior": _fmt_money(prior_rec, currency) if has_prior else "—"},
            {"name": "Prepayments & Other Current Assets", "current": _fmt_money(prepayments, currency), "prior": _fmt_money(prior_prep, currency) if has_prior else "—"},
            {"name": "Total Current Assets", "is_bold": True, "current": _fmt_money(current_assets, currency), "prior": _fmt_money(prior_ca, currency) if has_prior else "—"},
            {"name": "Property, Plant & Equipment / Fixed Assets", "current": _fmt_money(fixed_assets, currency), "prior": _fmt_money(prior_fa, currency) if has_prior else "—"},
            {"name": "Other Non-Current Assets", "current": _fmt_money(non_current_assets - fixed_assets, currency), "prior": _fmt_money(prior_nca - prior_fa, currency) if has_prior else "—"},
            {"name": "Total Non-Current Assets", "is_bold": True, "current": _fmt_money(non_current_assets, currency), "prior": _fmt_money(prior_nca, currency) if has_prior else "—"},
            {"name": "TOTAL ASSETS", "is_total": True, "is_bold": True, "current": _fmt_money(total_assets, currency), "prior": _fmt_money(prior_ta, currency) if has_prior else "—"},
            {"name": "LIABILITIES", "is_header": True, "is_bold": True, "current": "", "prior": ""},
            {"name": "Accounts Payable", "current": _fmt_money(payables, currency), "prior": _fmt_money(prior_pay, currency) if has_prior else "—"},
            {"name": "Other Current Liabilities", "current": _fmt_money(current_liabilities - payables, currency), "prior": _fmt_money(prior_cl - prior_pay, currency) if has_prior else "—"},
            {"name": "Total Current Liabilities", "is_bold": True, "current": _fmt_money(current_liabilities, currency), "prior": _fmt_money(prior_cl, currency) if has_prior else "—"},
            {"name": "Non-Current Liabilities", "current": _fmt_money(non_current_liabilities, currency), "prior": _fmt_money(prior_ncl, currency) if has_prior else "—"},
            {"name": "TOTAL LIABILITIES", "is_total": True, "is_bold": True, "current": _fmt_money(total_liabilities, currency), "prior": _fmt_money(prior_tl, currency) if has_prior else "—"},
            {"name": "EQUITY", "is_header": True, "is_bold": True, "current": "", "prior": ""},
            {"name": "Retained Earnings", "current": _fmt_money(retained_earnings, currency), "prior": _fmt_money(prior_re, currency) if has_prior else "—"},
            {"name": "Unallocated Earnings", "current": _fmt_money(unallocated_earnings, currency), "prior": _fmt_money(prior_ue, currency) if has_prior else "—"},
            {"name": "TOTAL EQUITY", "is_total": True, "is_bold": True, "current": _fmt_money(total_equity, currency), "prior": _fmt_money(prior_eq, currency) if has_prior else "—"},
            {"name": "TOTAL LIABILITIES & EQUITY", "is_total": True, "is_bold": True, "current": _fmt_money(total_liabilities + total_equity, currency), "prior": _fmt_money(prior_tl + prior_eq, currency) if has_prior else "—"},
        ]

        data.update({
            "total_assets": _build_kpi_variance(total_assets, prior_ta, currency, fmt="money", polarity="positive"),
            "current_assets": _build_kpi_variance(current_assets, prior_ca, currency, fmt="money", polarity="positive"),
            "non_current_assets": _build_kpi_variance(non_current_assets, prior_nca, currency, fmt="money", polarity="positive"),
            "fixed_assets": _build_kpi_variance(fixed_assets, prior_fa, currency, fmt="money", polarity="positive"),
            "total_liabilities": _build_kpi_variance(total_liabilities, prior_tl, currency, fmt="money", polarity="negative"),
            "current_liabilities": _build_kpi_variance(current_liabilities, prior_cl, currency, fmt="money", polarity="negative"),
            "non_current_liabilities": _build_kpi_variance(non_current_liabilities, prior_ncl, currency, fmt="money", polarity="negative"),
            "total_equity": _build_kpi_variance(total_equity, prior_eq, currency, fmt="money", polarity="positive"),
            "equity": _build_kpi_variance(total_equity, prior_eq, currency, fmt="money", polarity="positive"),
            "retained_earnings": _build_kpi_variance(retained_earnings, prior_re, currency, fmt="money", polarity="positive"),
            "unallocated_earnings": _build_kpi_variance(unallocated_earnings, prior_ue, currency, fmt="money", polarity="positive"),
            "current_ratio": _build_kpi_variance(cur_ratio, prior_cr, currency, fmt="ratio", polarity="positive"),
            "working_capital": _build_kpi_variance(nwc_val, prior_nwc, currency, fmt="money", polarity="positive"),
            "nwc": _build_kpi_variance(nwc_val, prior_nwc, currency, fmt="money", polarity="positive"),
            "cash": _build_kpi_variance(cash, prior_cash, currency, fmt="money", polarity="positive"),
            "bank_and_cash_accounts": _build_kpi_variance(cash, prior_cash, currency, fmt="money", polarity="positive"),
            "receivables": _build_kpi_variance(receivables, prior_rec, currency, fmt="money", polarity="neutral"),
            "accounts_receivable": _build_kpi_variance(receivables, prior_rec, currency, fmt="money", polarity="neutral"),
            "payables": _build_kpi_variance(payables, prior_pay, currency, fmt="money", polarity="negative"),
            "accounts_payable": _build_kpi_variance(payables, prior_pay, currency, fmt="money", polarity="negative"),
            "balance_sheet": bs_statement,
        })
    except Exception as e:
        logger.warning(f"Balance sheet domain query error: {e}")
