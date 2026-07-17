import os
import django
import sys
import asyncio
import json

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'doova_one_view.settings')
django.setup()

from doova_one_view.api.accounting.service import AccountingService

async def main():
    tenant_id = '4fa1b33d-870f-4681-a54e-52e9b12f6b99'
    
    try:
        res = await AccountingService.get_journal_cards(tenant_id)
        data = res.dict() if hasattr(res, 'dict') else res
        with open('response_dump.json', 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, default=str)
    except Exception as e:
        print(f"Error: {e}")

if __name__ == '__main__':
    asyncio.run(main())
