"""
Add dim_currencies table for currency dimension

This migration creates the currencies dimension table to store
currency information from Odoo (res.currency model).
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('odoo_app', '0001_initial'),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
            CREATE TABLE IF NOT EXISTS dim_currencies (
                id BIGSERIAL PRIMARY KEY,
                tenant_id UUID NOT NULL,
                odoo_id INTEGER NOT NULL,
                code VARCHAR(10) NOT NULL,
                symbol VARCHAR(10),
                is_active BOOLEAN DEFAULT TRUE,
                symbol_position VARCHAR(10) DEFAULT 'after',
                rounding DECIMAL(10, 6) DEFAULT 0.01,
                odoo_write_date TIMESTAMP,
                synced_at TIMESTAMP DEFAULT NOW(),
                UNIQUE (tenant_id, odoo_id)
            );
            
            CREATE INDEX IF NOT EXISTS idx_currencies_tenant 
                ON dim_currencies(tenant_id);
            CREATE INDEX IF NOT EXISTS idx_currencies_code 
                ON dim_currencies(tenant_id, code);
            CREATE INDEX IF NOT EXISTS idx_currencies_active 
                ON dim_currencies(tenant_id, is_active);
            """,
            reverse_sql="DROP TABLE IF EXISTS dim_currencies CASCADE;"
        ),
    ]
