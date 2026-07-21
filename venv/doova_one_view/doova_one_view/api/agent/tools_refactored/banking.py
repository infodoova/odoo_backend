# api/agent/tools_refactored/banking.py
from asgiref.sync import async_to_sync
from typing import Optional
from doova_one_view.api.accounting.service import AccountingService
from doova_one_view.api.agent.tools_refactored.common import run_query, normalize_company_ids, build_company_filter_sql

def get_bank_cash_summary_tool(
    tenant_id: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    company_id: Optional[int] = None,
    company_ids: Optional[list[int]] = None,
    base_currency: Optional[str] = None
) -> dict:
    selected = normalize_company_ids(company_id=company_id, companies=company_ids)
    data = async_to_sync(AccountingService.get_dashboard)(
        tenant_id=tenant_id,
        start_date=start_date,
        end_date=end_date,
        company_ids=selected,
        base_currency=base_currency
    )
    return {
        "tool_name": "get_bank_cash_summary_tool",
        "opening_cash_balance": data.get("opening_cash_balance", 0.0),
        "cash_in": data.get("cash_in", 0.0),
        "cash_out": data.get("cash_out", 0.0),
        "closing_cash_balance": data.get("closing_cash_balance", 0.0),
        "bank_balance": data.get("bank_balance", 0.0),
        "cash_flow_breakdown": data.get("cash_flow_breakdown", [])
    }

def get_journal_cards_tool(
    tenant_id: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    company_id: Optional[int] = None,
    company_ids: Optional[list[int]] = None,
    base_currency: Optional[str] = None
) -> dict:
    selected = normalize_company_ids(company_id=company_id, companies=company_ids)
    res = async_to_sync(AccountingService.get_journal_cards)(
        tenant_id=tenant_id,
        start_date=start_date,
        end_date=end_date,
        company_ids=selected,
        base_currency=base_currency
    )
    return {
        "tool_name": "get_journal_cards_tool",
        "data": res
    }

def get_bank_statement_summary_tool(
    tenant_id: str,
    company_id: Optional[int] = None,
    company_ids: Optional[list[int]] = None,
) -> dict:
    selected = normalize_company_ids(company_id=company_id, companies=company_ids)
    params = {"tenant_id": tenant_id}
    c_sql, c_params = build_company_filter_sql(tenant_id, selected, column_name="s.company_id", prefix="company")
    params.update(c_params)

    rows = run_query(f"""
        SELECT 
            s.odoo_name AS statement_name, 
            s.date, 
            s.balance_start, 
            s.balance_end_real, 
            s.currency_code
        FROM fact_bank_statements s
        WHERE s.tenant_id = :tenant_id {c_sql}
        ORDER BY s.date DESC
        LIMIT 20
    """, params)

    return {
        "tool_name": "get_bank_statement_summary_tool",
        "recent_statements": [
            {
                "statement": str(r.get("statement_name")),
                "date": str(r.get("date")),
                "opening_balance": float(r.get("balance_start") or 0),
                "closing_balance": float(r.get("balance_end_real") or 0),
                "currency": str(r.get("currency_code") or "")
            }
            for r in rows
        ]
    }
