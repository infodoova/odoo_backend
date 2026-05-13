import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "doova_one_view.settings")
django.setup()

from django.db import connection

def check_columns(table_name):
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT column_name FROM information_schema.columns WHERE table_name = '{table_name}'")
        columns = [row[0] for row in cursor.fetchall()]
        print(f"Columns in {table_name}:")
        for col in columns:
            print(f" - {col}")

if __name__ == "__main__":
    check_columns("fact_sales_order_lines")
    print("-" * 20)
    check_columns("fact_sales_orders")
