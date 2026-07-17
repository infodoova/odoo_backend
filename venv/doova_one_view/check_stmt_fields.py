import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'doova_one_view.settings')
django.setup()

from odoo_app.models import BankStatement

print([f.name for f in BankStatement._meta.fields])

qs = BankStatement.objects.filter(journal__odoo_id=152).order_by('-date', '-id')[:10]
for s in qs:
    print(f"Odoo ID: {s.odoo_id}, Date: {s.date}, Balance: {s.balance_end_real}, State: {s.state}")
    
s_2249 = BankStatement.objects.filter(odoo_id=2249).first()
if s_2249:
    print(f"Odoo ID: {s_2249.odoo_id}, Date: {s_2249.date}, Balance: {s_2249.balance_end_real}, State: {s_2249.state}")
