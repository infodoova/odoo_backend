from odoo_app.models.account_move_line import AccountMoveLine  
from django.db.models import Sum  
qs = AccountMoveLine.objects.filter(tenant_id='4fa1b33d-870f-4681-a54e-52e9b12f6b99', account_move__state='posted')  
for atype in ['income', 'expense', 'expense_direct_cost']:  
    res = qs.filter(account_type=atype).aggregate(tot_debit=Sum('debit'), tot_credit=Sum('credit'))  
    print(atype, res)  
