import os
import sys
import django
import asyncio
import json

sys.path.append(r"c:\Users\PC\Desktop\doova_one_view\odoo_backend\venv\doova_one_view")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "doova_one_view.settings")
django.setup()

from doova_one_view.api.accounting.service import AccountingService

async def main():
    tenant_id = '4fa1b33d-870f-4681-a54e-52e9b12f6b99'
    start_date = '2026-01-01'
    end_date = '2026-12-31'
    
    try:
        from odoo_app.models import Company
        company = await asyncio.to_thread(lambda: Company.objects.filter(tenant_id=tenant_id, name__icontains='supernova').first())
        company_id_param = [company.id] if company else None

        print(f"Fetching for Tenant: {tenant_id}, Company: {company.name if company else 'All'} (ID: {company_id_param})")

        dashboard = await AccountingService.get_dashboard(
            tenant_id=tenant_id,
            start_date=start_date,
            end_date=end_date,
            company_ids=company_id_param
        )
        
        data = {
            "opening_cash_balance": dashboard.get("opening_cash_balance"),
            "cash_in": dashboard.get("cash_in"),
            "cash_out": dashboard.get("cash_out"),
            "closing_cash_balance": dashboard.get("closing_cash_balance"),
            "bank_balance": dashboard.get("bank_balance"),
            "cash_flow_breakdown": dashboard.get("cash_flow_breakdown")
        }
        
        with open('bank_cash_dump_2026.json', 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, default=str)
            
        print("Successfully wrote response to bank_cash_dump_2026.json")
        print("\n--- Live Data Snippet ---")
        print(json.dumps(data, indent=2))
        
    except Exception as e:
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    asyncio.run(main())
