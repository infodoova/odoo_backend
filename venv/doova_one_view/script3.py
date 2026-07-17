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
    account_type='expense'
)

aggs = qs.values('account_code').annotate(
    balance=Sum('debit') - Sum('credit')
)

total = 0
for row in aggs:
    code = row['account_code']
    bal = row['balance'] or 0
    total += bal
    print(f"{code}: {bal}")

print(f"Total expense: {total}")
