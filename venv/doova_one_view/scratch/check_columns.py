import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'doova_one_view.settings')
from sqlalchemy import create_engine, text

e = create_engine(os.getenv('DATABASE_URL', 'postgresql://postgres:imamali1234@localhost:5432/odoo'))
conn = e.connect()

for table in ['fact_sales_order_lines', 'fact_sales_orders', 'fact_inventory_quants', 'dim_lots', 'fact_account_moves', 'fact_inventory_moves', 'dim_products']:
    print(f"\n=== {table} ===")
    rows = conn.execute(text(f"SELECT column_name FROM information_schema.columns WHERE table_name = '{table}' ORDER BY ordinal_position"))
    for r in rows:
        print(f"  {r[0]}")

conn.close()
