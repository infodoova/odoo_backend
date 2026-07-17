import os  
import django  
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'doova_one_view.settings')  
django.setup()  
from django.db import connection  
tenant_id = '4fa1b33d-870f-4681-a54e-52e9b12f6b99'  
with connection.cursor() as cursor:  
    cursor.execute(f" SELECT code, name, account_type FROM dim_chart_of_accounts WHERE tenant_id = '{tenant_id}' AND code LIKE '701%'")  
    for a in cursor.fetchall(): print(a)  
