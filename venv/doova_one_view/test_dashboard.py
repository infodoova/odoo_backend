import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'doova_one_view.settings')
django.setup()
from doova_one_view.api.accounting.service import AccountingService
import asyncio, json
from odoo_app.models import Company

async def main():
    company = Company.objects.get(name__icontains='supernov')
    tenant_id = str(company.tenant_id)
    dashboard = await AccountingService.get_dashboard(
        tenant_id, start_date="2026-01-01", end_date="2026-12-31", company_ids=[company.id]
    )
    print("Dashboard Revenue:", dashboard.get("total_revenue"))
    print("Dashboard Expenses:", dashboard.get("total_expenses"))
    print("Dashboard Net Profit:", dashboard.get("net_profit"))
    print("Dashboard Gross Profit:", dashboard.get("gross_profit"))
    
asyncio.run(main())
