import psycopg2

conn = psycopg2.connect('postgresql://postgres:123456@localhost:5432/odoo')
cur = conn.cursor()
cur.execute("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS odoo_username VARCHAR(255) DEFAULT ''")
cur.execute("UPDATE tenants SET odoo_username = %s WHERE id = %s", ('ali.chamas@odoo.com', '9f026f0a-6a55-49da-98a1-478a40fe4640'))
cur.execute("UPDATE tenants SET odoo_username = %s WHERE id = %s", ('ali.chamas@odoo.com', '78191733-c06a-4238-a44c-27fbbf66edf4'))
conn.commit()

cur.execute("SELECT id, name, odoo_url, odoo_database, odoo_username FROM tenants")
for r in cur.fetchall():
    print(r)
conn.close()
