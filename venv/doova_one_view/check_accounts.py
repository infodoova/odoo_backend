import os, django
from django.db.models import Sum
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'doova_one_view.settings')
django.setup()
from odoo_app.models import AccountMoveLine, Company, ChartOfAccounts

company = Company.objects.get(name__icontains='supernov')

# Get all account names for expense accounts
print('=== Chart of Accounts (expense-related) ===')
accounts = ChartOfAccounts.objects.filter(
    tenant_id=company.tenant_id,
    account_type__startswith='expense'
).order_by('code')
for acc in accounts:
    print(f'{acc.code} | {acc.account_type:30s} | {acc.name}')

# Also check what Odoo defines as 64* accounts
print('\n=== Specifically 64*, 67*, 69* accounts ===')
for acc in accounts:
    if acc.code.startswith('64') or acc.code.startswith('67') or acc.code.startswith('69') or acc.code.startswith('68'):
        print(f'{acc.code} | {acc.account_type:30s} | {acc.name}')
