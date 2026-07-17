import os
import sys
import django
import asyncio

sys.path.append(r"c:\Users\PC\Desktop\doova_one_view\odoo_backend\venv\doova_one_view")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "doova_one_view.settings")
django.setup()

from doova_one_view.api.tenants.service import TenantService

async def main():
    tenant_id = '4fa1b33d-870f-4681-a54e-52e9b12f6b99'
    print(f"Starting full sync for tenant: {tenant_id}")
    res = await TenantService.run_full_sync(tenant_id)
    print("Sync complete.")

if __name__ == "__main__":
    asyncio.run(main())
