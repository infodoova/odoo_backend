from django.db import migrations

def seed_roles(apps, schema_editor):
    Role = apps.get_model('odoo_app', 'Role')
    Permission = apps.get_model('odoo_app', 'Permission')

    # Manager permissions
    manager_perms = [
        'view_tenants', 'view_users', 'view_sales', 'export_sales', 'view_purchases',
        'export_purchases', 'view_accounting', 'export_accounting', 'view_inventory',
        'export_inventory', 'view_kpi', 'view_reports', 'export_reports', 'use_agent',
        'view_master_data'
    ]

    # Accountant permissions
    accountant_perms = [
        'view_sales', 'view_purchases', 'view_accounting', 'export_accounting',
        'view_inventory', 'view_kpi', 'view_reports', 'use_agent', 'view_master_data'
    ]

    # Owner permissions (All)
    owner_perms = [p.codename for p in Permission.objects.all()]

    roles_data = [
        {'name': 'owner', 'description': 'Full access to every feature', 'perms': owner_perms},
        {'name': 'manager', 'description': 'Managerial access with limited admin rights', 'perms': manager_perms},
        {'name': 'accountant', 'description': 'Access tailored for accounting and reporting', 'perms': accountant_perms},
    ]

    for r_data in roles_data:
        role, created = Role.objects.get_or_create(
            name=r_data['name'],
            defaults={'description': r_data['description']}
        )
        
        # Assign permissions
        perms = Permission.objects.filter(codename__in=r_data['perms'])
        role.permissions.set(perms)


def revert_roles(apps, schema_editor):
    Role = apps.get_model('odoo_app', 'Role')
    Role.objects.filter(name__in=['owner', 'manager', 'accountant']).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('odoo_app', '0017_seed_permissions'),
    ]

    operations = [
        migrations.RunPython(seed_roles, revert_roles),
    ]
