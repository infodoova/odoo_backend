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
    account_move__date__year=2026
)

aggs = qs.values('account_code', 'account_type').annotate(
    balance=Sum('debit') - Sum('credit')
)

balances = []
for row in aggs:
    balances.append(row['balance'] or 0)

# simple subset sum check for 10931142
target = 10931142
import itertools

found = False
for r in range(1, 4):
    for combo in itertools.combinations([b for b in balances if b != 0], r):
        if sum(combo) == target:
            print(f"Found combo matching target: {combo}")
            found = True

if not found:
    print("No combo up to size 3 found.")
