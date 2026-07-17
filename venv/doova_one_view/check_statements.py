import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'doova_one_view.settings')
django.setup()

from odoo_app.models import BankStatement

qs = BankStatement.objects.filter(journal__odoo_id=152)
print(f"Count of statements for journal 152: {qs.count()}")
for stmt in qs.order_by('-date', '-id')[:5]:
    print(f"ID: {stmt.id}, Odoo ID: {stmt.odoo_id}, Date: {stmt.date}, Balance end: {stmt.balance_end_real}")

# Also check Odoo ID 2249 specifically
stmt_2249 = BankStatement.objects.filter(odoo_id=2249).first()
if stmt_2249:
    print(f"\nFound Statement 2249: Date {stmt_2249.date}, balance {stmt_2249.balance_end_real}, Journal Odoo ID: {stmt_2249.journal.odoo_id}")
else:
    print("\nStatement 2249 NOT FOUND")
