import os, django
from django.db.models import Sum, F
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'doova_one_view.settings')
django.setup()
from odoo_app.models import AccountMoveLine, Company

company = Company.objects.get(name__icontains='supernov')
qs = AccountMoveLine.objects.filter(
    account_move__tenant_id=company.tenant_id,
    account_move__company_id=company.id,
    account_move__state='posted',
    account_move__date__year=2026
)

aggs = qs.values('account_type').annotate(
    total_debit=Sum('debit'),
    total_credit=Sum('credit')
)

for row in aggs:
    balance = (row['total_debit'] or 0) - (row['total_credit'] or 0)
    print(f"{row['account_type']}: {balance}")
