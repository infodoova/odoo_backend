from django.db import migrations


STALE_PERMISSIONS = [
    # Generic/broad permissions replaced by granular ones
    "view_users",
    "view_sales",
    "export_sales",
    "view_purchases",
    "export_purchases",
    "view_accounting",
    "export_accounting",
    "view_inventory",
    "export_inventory",
    # Orphaned — no route ever enforces these
    "export_reports",
    "view_master_data",
    "view_notifications",
    "view_settings",
    "view_support",
    "view_sales_order_lines",
    "view_sales_customers",
    "view_purchase_order_lines",
    "view_finance_invoices",
    "view_finance_expenses",
    "view_finance_budget",
    "view_storage",
]


def delete_stale_permissions(apps, schema_editor):
    Permission = apps.get_model('odoo_app', 'Permission')
    RolePermission = apps.get_model('odoo_app', 'RolePermission')

    for codename in STALE_PERMISSIONS:
        try:
            perm = Permission.objects.get(codename=codename)
            # Remove all role assignments first
            RolePermission.objects.filter(permission=perm).delete()
            perm.delete()
        except Permission.DoesNotExist:
            pass  # Already gone — idempotent


def reverse_func(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('odoo_app', '0028_update_rbac_permissions'),
    ]

    operations = [
        migrations.RunPython(delete_stale_permissions, reverse_func),
    ]
