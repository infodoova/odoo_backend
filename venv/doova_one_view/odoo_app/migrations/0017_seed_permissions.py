from django.db import migrations

def seed_permissions(apps, schema_editor):
    Permission = apps.get_model('odoo_app', 'Permission')
    
    permissions_to_create = [
        {'codename': 'view_tenants', 'description': 'View tenant list'},
        {'codename': 'manage_tenants', 'description': 'Create, update, and delete tenants'},
        {'codename': 'view_users', 'description': 'View user list and details'},
        {'codename': 'manage_users', 'description': 'Create and deactivate users'},
        {'codename': 'manage_roles', 'description': 'Create roles, assign permissions to roles, assign roles to users'},
        {'codename': 'view_sales', 'description': 'View sales orders and summaries'},
        {'codename': 'export_sales', 'description': 'Export sales data to file'},
        {'codename': 'view_purchases', 'description': 'View purchase orders'},
        {'codename': 'export_purchases', 'description': 'Export purchase data to file'},
        {'codename': 'view_accounting', 'description': 'View journal entries and account moves'},
        {'codename': 'export_accounting', 'description': 'Export accounting data to file'},
        {'codename': 'view_inventory', 'description': 'View stock and inventory levels'},
        {'codename': 'export_inventory', 'description': 'Export inventory data to file'},
        {'codename': 'view_kpi', 'description': 'View KPI dashboards'},
        {'codename': 'view_reports', 'description': 'View generated reports'},
        {'codename': 'export_reports', 'description': 'Download and export reports'},
        {'codename': 'use_agent', 'description': 'Send queries to the AI agent'},
        {'codename': 'view_master_data', 'description': 'View partners, products, and companies'},
    ]

    for p_data in permissions_to_create:
        Permission.objects.get_or_create(
            codename=p_data['codename'],
            defaults={'description': p_data['description']}
        )

def revert_permissions(apps, schema_editor):
    Permission = apps.get_model('odoo_app', 'Permission')
    codenames = [
        'view_tenants', 'manage_tenants', 'view_users', 'manage_users', 'manage_roles',
        'view_sales', 'export_sales', 'view_purchases', 'export_purchases',
        'view_accounting', 'export_accounting', 'view_inventory', 'export_inventory',
        'view_kpi', 'view_reports', 'export_reports', 'use_agent', 'view_master_data'
    ]
    Permission.objects.filter(codename__in=codenames).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('odoo_app', '0016_currency_currencyrate_currency_idx_currencies_tenant_and_more'),
    ]

    operations = [
        migrations.RunPython(seed_permissions, revert_permissions),
    ]
