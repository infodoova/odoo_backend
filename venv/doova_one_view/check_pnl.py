import os, django
from django.db.models import Sum
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'doova_one_view.settings')
django.setup()
from odoo_app.models import AccountMoveLine, Company

company = Company.objects.get(name__icontains='supernov')
qs = AccountMoveLine.objects.filter(
    account_move__tenant_id=company.tenant_id,
    account_move__company_id=company.id,
    account_move__state='posted',
    account_move__date__year=2026,
).exclude(
    account_code__in=['60520003', '60510002']
)

aggs = qs.values('account_code', 'account_type').annotate(
    balance=Sum('debit') - Sum('credit')
).order_by('account_code')

revenue = 0
cogs = 0
opex = 0
taxes_interest = 0
depreciation = 0

print('=== INCOME ACCOUNTS ===')
for row in aggs:
    atype = row['account_type'] or ''
    acode = row['account_code'] or ''
    bal = float(row['balance'] or 0)
    
    if atype.startswith('income'):
        print(f"  {acode}: {bal:>15,.0f}  (credit-debit = {-bal:>15,.0f})")
        revenue += -bal  # credit - debit

print('\n=== COGS (expense_direct_cost) ===')
for row in aggs:
    atype = row['account_type'] or ''
    acode = row['account_code'] or ''
    bal = float(row['balance'] or 0)
    if atype == 'expense_direct_cost':
        print(f"  {acode}: {bal:>15,.0f}")
        cogs += bal

print('\n=== DEPRECIATION (expense_depreciation) ===')
for row in aggs:
    atype = row['account_type'] or ''
    acode = row['account_code'] or ''
    bal = float(row['balance'] or 0)
    if atype == 'expense_depreciation':
        print(f"  {acode}: {bal:>15,.0f}")
        depreciation += bal

print('\n=== EXPENSE ACCOUNTS (by code prefix) ===')
for row in aggs:
    atype = row['account_type'] or ''
    acode = row['account_code'] or ''
    bal = float(row['balance'] or 0)
    if atype == 'expense':
        prefix = acode[:2]
        label = ''
        if prefix in ('64',):
            label = '[TAX]'
            taxes_interest += bal
        elif prefix in ('67',):
            label = '[FINANCIAL/INTEREST]'
            taxes_interest += bal
        elif prefix in ('69',):
            label = '[INCOME TAX]'
            taxes_interest += bal
        else:
            label = '[OPEX]'
            opex += bal
        print(f"  {acode}: {bal:>15,.0f}  {label}")

gross_profit = revenue - cogs
total_expenses_below_gp = opex + depreciation + taxes_interest
ebit = gross_profit - opex - depreciation
net_profit = ebit - taxes_interest

print(f'\n========== P&L SUMMARY ==========')
print(f'Revenue:              {revenue:>15,.0f}')
print(f'COGS:                 {cogs:>15,.0f}')
print(f'Gross Profit:         {gross_profit:>15,.0f}')
print(f'OpEx:                 {opex:>15,.0f}')
print(f'Depreciation:         {depreciation:>15,.0f}')
print(f'Taxes/Interest:       {taxes_interest:>15,.0f}')
print(f'EBIT:                 {ebit:>15,.0f}')
print(f'Net Profit:           {net_profit:>15,.0f}')
print(f'Check (GP-all exp):   {gross_profit - total_expenses_below_gp:>15,.0f}')
