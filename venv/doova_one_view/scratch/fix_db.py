from django.db import connection
import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "doova_one_view.settings")
django.setup()

with connection.cursor() as cursor:
    print("Adding api_key_encrypted column...")
    cursor.execute("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS api_key_encrypted bytea;")
    
    print("Checking for other potentially missing columns...")
    # Add other columns if needed (based on model)
    cursor.execute("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS sync_status varchar(50) DEFAULT 'pending';")
    cursor.execute("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS last_sync_at timestamp with time zone;")
    cursor.execute("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS created_at timestamp with time zone;")
    cursor.execute("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS updated_at timestamp with time zone;")

print("Done.")
