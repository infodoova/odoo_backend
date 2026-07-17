import os
import django
import sys
import asyncio

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
    
    print("Fetching fields for account.journal...")
    fields = odoo.call_kw('account.journal', 'fields_get', args=[], kwargs={'attributes': ['string', 'type']})
    dashboard_fields = {k: v for k, v in fields.items() if 'dashboard' in k.lower() or 'kanban' in k.lower() or 'balance' in k.lower()}
    for k, v in dashboard_fields.items():
        print(f"{k}: {v}")
        
    print("\nReading kanban_dashboard for Cash POS Maria Cano (152)...")
    try:
        res = odoo.search_read('account.journal', domain=[('id', '=', 152)], fields=['name', 'kanban_dashboard'])
        print(res)
    except Exception as e:
        print(f"Error reading: {e}")

if __name__ == '__main__':
    main()
