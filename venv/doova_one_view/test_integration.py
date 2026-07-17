import os, django, asyncio, json
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'doova_one_view.settings')
django.setup()
from odoo_app.models import Company
from doova_one_view.api.accounting.service import AccountingService

def get_company():
    return Company.objects.get(name__icontains='supernov')

async def main():
    from asgiref.sync import sync_to_async
    company = await sync_to_async(get_company)()
    tenant_id = str(company.tenant_id)
    cids = [company.id]
    
    pnl = await AccountingService.get_pnl_summary(tenant_id, '2026-01-01', '2026-12-31', cids)
    dash = await AccountingService.get_dashboard(tenant_id, '2026-01-01', '2026-12-31', cids)
    
    print('=== P&L ===')
    print(json.dumps(pnl, indent=2))
    print()
    print('=== Dashboard (key metrics) ===')
    print('  Revenue:     ', dash["total_revenue"]["value"])
    print('  Expenses:    ', dash["total_expenses"]["value"])
    print('  Net Profit:  ', dash["net_profit"]["value"])
    print('  Gross Profit:', dash["gross_profit"]["value"])
    print('  EBIT:        ', dash["ebit"]["value"])
    
    print()
    print('=== Cross-check ===')
    print('  P&L Revenue == Dashboard Revenue:      ', pnl["revenue"] == dash["total_revenue"]["value"])
    print('  P&L Net Profit == Dashboard Net Profit: ', pnl["net_profit"] == dash["net_profit"]["value"])
    print('  P&L Gross Profit == Dashboard GP:       ', pnl["gross_profit"] == dash["gross_profit"]["value"])
    print('  P&L EBIT == Dashboard EBIT:             ', pnl["ebit"] == dash["ebit"]["value"])

asyncio.run(main())
