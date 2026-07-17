import os
import django
import sys
import json

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'doova_one_view.settings')
django.setup()

from doova_one_view.api.tenants.service import TenantService

def main():
    tenant_id = '4fa1b33d-870f-4681-a54e-52e9b12f6b99'
    
    from odoo_app.models import Tenant
    from doova_one_view.api.common.utils import decrypt_api_key
    from odoo_app.etl.config import TenantConfig
    from odoo_app.etl.clients.odoo_client import OdooClient
    import django.conf
    
    tenant = Tenant.objects.get(id=tenant_id)
    api_key = decrypt_api_key(tenant.api_key_encrypted)
    
    tenant_config = TenantConfig(
        tenant_id=str(tenant.id),
        name=tenant.name,
        odoo_url=tenant.odoo_url,
        odoo_database=tenant.odoo_database,
        odoo_username=getattr(django.conf.settings, 'ODOO_USERNAME', ''),
        odoo_api_key=api_key
    )
    odoo = OdooClient(tenant_config)
    
    # Read local response dump
    with open('response_dump.json', 'r', encoding='utf-8') as f:
        local_data = json.load(f)
        
    local_journals = {item['id']: item for item in local_data['items']}
    odoo_ids = list(local_journals.keys())
    
    print(f"Fetching kanban_dashboard for {len(odoo_ids)} journals from Odoo...")
    try:
        odoo_journals = odoo.search_read('account.journal', domain=[('id', 'in', odoo_ids)], fields=['name', 'type', 'kanban_dashboard'])
        
        def safe_print(s):
            print(str(s).replace('\\ufeff', '').encode('ascii', 'ignore').decode('ascii'))
            
        for oj in odoo_journals:
            jid = oj['id']
            name = oj['name']
            jtype = oj['type']
            dashboard_str = oj.get('kanban_dashboard')
            if not dashboard_str:
                continue
                
            dashboard = json.loads(dashboard_str)
            local_j = local_journals.get(jid)
            if not local_j:
                continue
                
            local_metrics = local_j['metrics']
            
            safe_print(f"\\n--- Journal: {name} (ID: {jid}, Type: {jtype}) ---")
            
            if jtype in ['bank', 'cash']:
                safe_print(f"  [Bank/Cash]")
                safe_print(f"    Odoo is_sample_data: {dashboard.get('is_sample_data')}")
                safe_print(f"    Odoo account_balance: {dashboard.get('account_balance')} | Local gl_balance: {local_metrics.get('gl_balance')}")
                safe_print(f"    Odoo last_balance: {dashboard.get('last_balance')} | Local latest_statement_balance: {local_metrics.get('latest_statement_balance')}")
                safe_print(f"    Odoo outstanding_pay_account_balance: {dashboard.get('outstanding_pay_account_balance', 'N/A')} | Local outstanding_payments: {local_metrics.get('outstanding_payments')}")
                safe_print(f"    Odoo misc_operations_balance: {dashboard.get('misc_operations_balance', 'N/A')} | Local misc_operations_amount: {local_metrics.get('misc_operations_amount')}")
                safe_print(f"    Odoo last_statement_id: {dashboard.get('last_statement_id', 'N/A')}")
            
            elif jtype in ['sale', 'purchase']:
                safe_print(f"  [Sale/Purchase]")
                safe_print(f"    Odoo amount_unpaid (sum_waiting): {dashboard.get('sum_waiting')} | Local unpaid_amount: {local_metrics.get('unpaid_amount')}")
                safe_print(f"    Odoo number_unpaid (number_waiting): {dashboard.get('number_waiting')} | Local unpaid_count: {local_metrics.get('unpaid_count')}")
                safe_print(f"    Odoo amount_draft (sum_draft): {dashboard.get('sum_draft')} | Local draft_amount: {local_metrics.get('draft_amount')}")
                safe_print(f"    Odoo number_draft: {dashboard.get('number_draft')} | Local draft_count: {local_metrics.get('draft_count')}")
                safe_print(f"    Odoo amount_late (sum_late): {dashboard.get('sum_late')} | Local late_amount: {local_metrics.get('late_amount')}")
                safe_print(f"    Odoo number_late: {dashboard.get('number_late')} | Local late_count: {local_metrics.get('late_count')}")
            
            else:
                safe_print(f"  [General]")
                safe_print(f"    Odoo has kanban_dashboard: {list(dashboard.keys())}")
                
    except Exception as e:
        print(f"Error reading: {e}")

if __name__ == '__main__':
    main()
