from django.db import connection
import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "doova_one_view.settings")
django.setup()

with connection.cursor() as cursor:
    cursor.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
    tables = [row[0] for row in cursor.fetchall()]
    print("Tables in database:")
    for t in sorted(tables):
        print(f" - {t}")
