import os
import django
import sys
import asyncio

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'doova_one_view.settings')
django.setup()

from odoo_app.models import Tenant
from doova_one_view.api.common.utils import decrypt_api_key
from odoo_app.etl.config import TenantConfig
import django.conf
from odoo_app.etl.clients.odoo_client import OdooClient

def main():
    tenant_id = '4fa1b33d-870f-4681-a54e-52e9b12f6b99'
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
    
    # 2406 is Cash Maria Cano (53000017)
    domain = [['account_id', '=', 2406], ['parent_state', '=', 'posted']]
    fields = ['id', 'debit', 'credit', 'balance', 'amount_currency', 'move_id']
    
    lines = odoo.search_read('account.move.line', domain, fields)
    
    tot_bal = sum(l.get('balance', 0) for l in lines)
    print(f"Odoo Move Lines Count: {len(lines)}")
    print(f"Odoo Move Lines Total Balance: {tot_bal}")

if __name__ == '__main__':
    main()
