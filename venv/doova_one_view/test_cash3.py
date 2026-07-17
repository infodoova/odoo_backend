import os, django
from django.db.models import Sum
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'doova_one_view.settings')
django.setup()
from odoo_app.models import AccountMoveLine, Company
cid = Company.objects.get(name__icontains='supernov').id
start_date = '2026-01-01'
end_date = '2026-12-31'

# Group cash moves by AccountMove to find the NET cash effect per transaction
qs = AccountMoveLine.objects.filter(
    account_move__company_id=cid,
    account_move__state='posted',
    account_move__date__gte=start_date,
    account_move__date__lte=end_date,
    account_type='asset_cash'
).values('account_move_id').annotate(
    net_cash=Sum('debit') - Sum('credit')
)

cash_in = 0.0
cash_out = 0.0

for row in qs:
    nc = float(row['net_cash'] or 0)
    # ignore floating point zeroes
    if nc > 0.01:
        cash_in += nc
    elif nc < -0.01:
        cash_out += abs(nc)

print(f"Cash In (excluding internal transfers):  {cash_in:,.2f}")
print(f"Cash Out (excluding internal transfers): {cash_out:,.2f}")
print(f"Net Increase:                          {cash_in - cash_out:,.2f}")
