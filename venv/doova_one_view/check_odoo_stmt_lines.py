import os
import django
import sys

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'doova_one_view.settings')
django.setup()

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
    
    try:
        res = odoo.search_read('account.bank.statement', domain=[('journal_id', '=', 152)], fields=['name', 'date', 'balance_end_real', 'line_ids'], limit=15, order='date desc, id desc')
        print(f"Odoo Statements for Journal 152:")
        for r in res:
            print(f"ID: {r['id']}, Date: {r['date']}, Balance: {r['balance_end_real']}, Lines Count: {len(r.get('line_ids', []))}")
    except Exception as e:
        print(f"Error reading statements: {e}")

if __name__ == '__main__':
    main()
