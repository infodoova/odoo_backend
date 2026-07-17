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
    account_type__startswith='expense',
).exclude(
    account_code__in=['60520003', '60510002']
).exclude(
    account_type='expense_direct_cost'
)

aggs = qs.values('account_code', 'account_name').annotate(
    balance=Sum('debit') - Sum('credit')
).order_by('-balance')

for row in aggs:
    code = row['account_code'] or 'N/A'
    name = row['account_name'] or 'N/A'
    bal = float(row['balance'] or 0)
    print(f'{code:12s} | {bal:>15,.0f} | {name}')
