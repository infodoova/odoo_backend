file_path = r'c:\Users\PC\Desktop\doova_one_view\odoo_backend\venv\doova_one_view\doova_one_view\api\accounting\routes.py'
with open(file_path, 'r') as f:
    content = f.read()

# 1. Update import
old_import = 'from doova_one_view.api.accounting.schemas import SearchRequest, ProfitAndLossSummary'
new_import = 'from doova_one_view.api.accounting.schemas import SearchRequest, ProfitAndLossSummary, ExpenseBreakdownResponse'
content = content.replace(old_import, new_import)

# 2. Add route after pnl route
old_block = '    return ProfitAndLossSummary(**data)\n\n\n\n\n@router.get(\"/{tenant_id}/kpis\")'
new_block = '''    return ProfitAndLossSummary(**data)


@router.get("/{tenant_id}/expense-breakdown", response_model=ExpenseBreakdownResponse)
async def get_expense_breakdown(
    tenant_id: str,
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    company_id: Optional[int] = Query(None),
    companies: Optional[str] = Query(None),
    base_currency: Optional[str] = Query(None, description="Target currency for financial values"),
    user: AppUser = Depends(get_current_user),
) -> ExpenseBreakdownResponse:
    """Expense breakdown by category (Rent, Salaries, Purchases, etc.)."""
    await TenantService.get_tenant(tenant_id, str(user.id))
    data = await AccountingService.get_expense_breakdown(
        tenant_id,
        start_date or date_from,
        end_date or date_to,
        _company_ids(company_id, companies),
        base_currency,
    )
    return ExpenseBreakdownResponse(**data)


@router.get("/{tenant_id}/kpis")'''

content = content.replace(old_block, new_block)

with open(file_path, 'w') as f:
    f.write(content)
print('Done.')
