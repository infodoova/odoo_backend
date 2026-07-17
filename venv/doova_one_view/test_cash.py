import os, django
from django.db.models import Sum
from datetime import datetime
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'doova_one_view.settings')
django.setup()
from odoo_app.models import AccountMoveLine, Company, ChartOfAccounts

company = Company.objects.get(name__icontains='supernov')
tenant_id = company.tenant_id
cid = company.id

start_date = '2026-01-01'
end_date = '2026-12-31'

# 1. Opening Balance (all posted moves before start_date)
opening_qs = AccountMoveLine.objects.filter(
    account_move__tenant_id=tenant_id,
    account_move__company_id=cid,
    account_move__state='posted',
    account_move__date__lt=start_date,
    account_type='asset_cash'
)
opening_agg = opening_qs.aggregate(
    total_debit=Sum('debit'),
    total_credit=Sum('credit')
)
open_debit = float(opening_agg['total_debit'] or 0)
open_credit = float(opening_agg['total_credit'] or 0)
opening_balance = open_debit - open_credit

# 2. Cash In / Out (moves between start_date and end_date)
period_qs = AccountMoveLine.objects.filter(
    account_move__tenant_id=tenant_id,
    account_move__company_id=cid,
    account_move__state='posted',
    account_move__date__gte=start_date,
    account_move__date__lte=end_date,
    account_type='asset_cash'
)
period_agg = period_qs.aggregate(
    cash_in=Sum('debit'),
    cash_out=Sum('credit')
)
cash_in = float(period_agg['cash_in'] or 0)
cash_out = float(period_agg['cash_out'] or 0)

# 3. Closing Balance
closing_balance = opening_balance + cash_in - cash_out

# 4. Bank account breakdown
accounts = ChartOfAccounts.objects.filter(
    tenant_id=tenant_id,
    account_type='asset_cash'
).values('code', 'name')

account_dict = {a['code']: a['name'] for a in accounts}

# Cumulative balance per account up to end_date
closing_qs = AccountMoveLine.objects.filter(
    account_move__tenant_id=tenant_id,
    account_move__company_id=cid,
    account_move__state='posted',
    account_move__date__lte=end_date,
    account_type='asset_cash'
).values('account_code').annotate(
    debit=Sum('debit'),
    credit=Sum('credit')
)

print(f"Opening Balance: {opening_balance:,.2f}")
print(f"Cash In:         {cash_in:,.2f}")
print(f"Cash Out:        {cash_out:,.2f}")
print(f"Closing Balance: {closing_balance:,.2f}")
print("\nAccount Breakdown:")
for row in closing_qs:
    code = row['account_code']
    name = account_dict.get(code, 'Unknown')
    bal = float(row['debit'] or 0) - float(row['credit'] or 0)
    print(f"  {code} | {name:30s} | {bal:,.2f}")

