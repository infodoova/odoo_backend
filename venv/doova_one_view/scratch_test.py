import os
import django
import sys
import asyncio

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'doova_one_view.settings')
django.setup()

from odoo_app.models import AccountMoveLine
from django.db.models import Sum

tenant_id = '4fa1b33d-870f-4681-a54e-52e9b12f6b99'
odoo_journal_id = 152  # Cash POS Maria Cano
default_account_code = '53000007'

# Total GL balance
gl_agg = AccountMoveLine.objects.filter(
    tenant_id=tenant_id,
    account_code=default_account_code,
    account_move__state='posted'
).aggregate(d=Sum('debit'), c=Sum('credit'))
gl_bal = float(gl_agg['d'] or 0) - float(gl_agg['c'] or 0)

# Balance created by the journal itself
journal_agg = AccountMoveLine.objects.filter(
    tenant_id=tenant_id,
    account_code=default_account_code,
    account_move__state='posted',
    account_move__journal__odoo_id=odoo_journal_id
).aggregate(d=Sum('debit'), c=Sum('credit'))
journal_bal = float(journal_agg['d'] or 0) - float(journal_agg['c'] or 0)

print(f"GL Balance: {gl_bal}")
print(f"Journal's own balance: {journal_bal}")
print(f"Misc operations (Difference): {gl_bal - journal_bal}")

# Also let's check Outstanding Receipts and Payments
# Outstanding receipts are usually on a specific outstanding receipt account.
