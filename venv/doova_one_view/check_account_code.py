import os
import django
import sys
import json

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'doova_one_view.settings')
django.setup()

from odoo_app.models import AccountMoveLine, AccountJournal

tenant_id = '4fa1b33d-870f-4681-a54e-52e9b12f6b99'

# Cash POS Maria Cano
j = AccountJournal.objects.get(tenant_id=tenant_id, odoo_id=152)
print(f"Cash POS default_account_code: {j.default_account_code}")

lines = AccountMoveLine.objects.filter(
    tenant_id=tenant_id,
    account_code=j.default_account_code,
    account_move__state='posted'
).values('company__name', 'account_name').annotate(
    d=django.db.models.Sum('debit'),
    c=django.db.models.Sum('credit')
)

for l in lines:
    bal = float(l['d'] or 0) - float(l['c'] or 0)
    print(f"Company: {l['company__name']}, Account: {l['account_name']}, Balance: {bal}")
