import os
import django
import sys
import asyncio

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'doova_one_view.settings')
django.setup()

from odoo_app.models import Tenant
from doova_one_view.api.common.utils import decrypt_api_key
from odoo_app.etl.config import TenantConfig
from odoo_app.etl.syncs.journal_synchronizer import JournalSynchronizer
import django.conf
from odoo_app.etl.clients.odoo_client import OdooClient
from odoo_app.etl.managers.database_manager import DatabaseManager

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
    
    db_config = django.conf.settings.DATABASES['default']
    db_conn_string = (
        f"host={db_config.get('HOST', 'localhost')} "
        f"port={db_config.get('PORT', 5432)} "
        f"dbname={db_config.get('NAME')} "
        f"user={db_config.get('USER')} "
        f"password={db_config.get('PASSWORD')}"
    )
    
    odoo = OdooClient(tenant_config)
    db = DatabaseManager(db_conn_string)
    db.connect()
    
    sync = JournalSynchronizer(odoo, db)
    print("Running Journal sync...")
    synced, failed = sync.sync(tenant_id)
    print(f"Sync complete. Synced: {synced}, Failed: {failed}")
    db.close()

if __name__ == '__main__':
    main()
