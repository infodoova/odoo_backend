import asyncio  
from doova_one_view.api.tenants.service import TenantService  
tenant_id = '4fa1b33d-870f-4681-a54e-52e9b12f6b99'  
asyncio.run(TenantService.run_full_sync(tenant_id))  
