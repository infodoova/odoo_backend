import os, django
from django.db.models import Sum
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'doova_one_view.settings')
django.setup()
from odoo_app.models import AccountMoveLine, Company
cid = Company.objects.get(name__icontains='supernov').id
start_date = '2026-01-01'
end_date = '2026-12-31'

# Find all moves that have a line hitting an asset_cash account
cash_moves_qs = AccountMoveLine.objects.filter(
    account_move__company_id=cid,
    account_move__state='posted',
    account_move__date__gte=start_date,
    account_move__date__lte=end_date,
    account_type='asset_cash'
).values_list('account_move_id', flat=True)

# Now, group the lines of THOSE moves by account code/type
lines = AccountMoveLine.objects.filter(
    account_move_id__in=cash_moves_qs,
    account_type__isnull=False
).exclude(account_type='asset_cash').values('account_code', 'account_name').annotate(
    net=Sum('credit') - Sum('debit')
).order_by('-net')

print('Counterparty accounts in the SAME Journal Entries as Cash:')
for l in lines:
    print(f"{l['account_code']:10s} {l['account_name']:40s} {float(l['net'] or 0):,.2f}")
