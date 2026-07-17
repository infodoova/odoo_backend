import os
import django
import sys
import asyncio

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'doova_one_view.settings')
django.setup()

from doova_one_view.api.tenants.service import TenantService

async def main():
    tenant_id = '4fa1b33d-870f-4681-a54e-52e9b12f6b99'
    print(f"Starting full sync for tenant {tenant_id}...")
    try:
        response = await TenantService.run_full_sync(tenant_id)
        print("Full sync completed successfully!")
        print(response)
    except Exception as e:
        print(f"Full sync failed: {e}")

if __name__ == '__main__':
    asyncio.run(main())
