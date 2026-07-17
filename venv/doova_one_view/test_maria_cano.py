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
    
    print("Calling get_journal_dashboard_datas for Cash POS Maria Cano (ID: 152)...")
    res = odoo.call_kw('account.journal', 'get_journal_dashboard_datas', args=[[152]])
    print(f"Dashboard Data: {res}")

if __name__ == '__main__':
    main()
