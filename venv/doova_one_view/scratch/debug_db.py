from django.db import connection
import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "doova_one_view.settings")
django.setup()

db_info = connection.settings_dict
print(f"Connecting to:")
print(f"  ENGINE:   {db_info.get('ENGINE')}")
print(f"  NAME:     {db_info.get('NAME')}")
print(f"  USER:     {db_info.get('USER')}")
print(f"  HOST:     {db_info.get('HOST')}")
print(f"  PORT:     {db_info.get('PORT')}")

with connection.cursor() as cursor:
    cursor.execute("SELECT current_database(), current_user, inet_server_addr(), inet_server_port()")
    row = cursor.fetchone()
    print("\nDatabase Verified via SQL:")
    print(f"  Current DB:   {row[0]}")
    print(f"  Current User: {row[1]}")
    print(f"  Server Addr:  {row[2]}")
    print(f"  Server Port:  {row[3]}")

    cursor.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
    tables = [r[0] for r in cursor.fetchall()]
    print(f"\nFound {len(tables)} tables in 'public' schema.")
    for t in sorted(tables):
        print(f"  - {t}")
