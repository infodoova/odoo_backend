"""
Create the permissions the API checks but the database does not have.

The routes require 15 permission codenames that were never created (or were removed): every
CSV/Excel export, report schedules (manage_reports) and file storage (manage_storage). Because
the codename did not exist, no role could hold it, so every non-superuser, owners included, got
403 on those endpoints.

Grants follow the existing role design:
- an export is given to a role only if the role can already view that data, and only for the
  areas the role could export before (sales, purchases, accounting, inventory);
- report schedules go to the roles that manage alert schedules (owner, manager);
- file storage goes to the roles that work with storage (owner, manager, inventory clerk).
Custom roles are left unchanged; the owner role receives everything.
"""

from django.db import migrations

NEW_PERMISSIONS = {
    "export_sales_orders": "Export sales orders",
    "export_purchase_orders": "Export purchase orders",
    "export_accounting_moves": "Export journal entries and invoices",
    "export_account_journals": "Export accounting journals",
    "export_account_reconciles": "Export payment reconciliations",
    "export_bank_statements": "Export bank statements",
    "export_chart_of_accounts": "Export the chart of accounts",
    "export_inventory_moves": "Export stock moves",
    "export_inventory_pickings": "Export transfers (pickings)",
    "export_inventory_quants": "Export stock on hand",
    "export_lots": "Export lots and serial numbers",
    "export_partners": "Export customers and suppliers",
    "export_products": "Export products",
    "manage_reports": "Create, update, delete and send report schedules",
    "manage_storage": "Upload, download and delete stored files",
}

# export permission -> (business areas it belongs to, view permission it requires)
EXPORT_RULES = {
    "export_sales_orders": ({"sales"}, "view_sales_orders"),
    "export_purchase_orders": ({"purchases"}, "view_purchase_orders"),
    "export_accounting_moves": ({"accounting"}, "view_accounting_moves"),
    "export_account_journals": ({"accounting"}, "view_account_journals"),
    "export_account_reconciles": ({"accounting"}, "view_account_reconciles"),
    "export_bank_statements": ({"accounting"}, "view_bank_statements"),
    "export_chart_of_accounts": ({"accounting"}, "view_chart_of_accounts"),
    "export_inventory_moves": ({"inventory"}, "view_inventory_moves"),
    "export_inventory_pickings": ({"inventory"}, "view_inventory_pickings"),
    "export_inventory_quants": ({"inventory"}, "view_inventory_quants"),
    "export_lots": ({"inventory"}, "view_lots"),
    "export_partners": ({"sales", "purchases", "accounting"}, "view_partners"),
    "export_products": ({"sales", "purchases", "inventory"}, "view_products"),
}

# Areas each built-in role could export (from the role design in seed_rbac).
EXPORT_AREAS = {
    "manager": {"sales", "purchases", "accounting", "inventory"},
    "accountant": {"accounting"},
    "inventory_clerk": {"inventory"},
    "sales_rep": {"sales"},
}
MANAGE_REPORTS_ROLES = {"manager"}
MANAGE_STORAGE_ROLES = {"manager", "inventory_clerk"}


def grants_for(role_name, role_perms):
    """Codenames the built-in role ``role_name`` should receive (owner: all)."""
    if role_name == "owner":
        return set(NEW_PERMISSIONS)
    out = set()
    areas = EXPORT_AREAS.get(role_name, set())
    for codename, (needed_areas, view_perm) in EXPORT_RULES.items():
        if areas & needed_areas and view_perm in role_perms:
            out.add(codename)
    if role_name in MANAGE_REPORTS_ROLES:
        out.add("manage_reports")
    if role_name in MANAGE_STORAGE_ROLES:
        out.add("manage_storage")
    return out


def forwards(apps, schema_editor):
    Permission = apps.get_model("odoo_app", "Permission")
    Role = apps.get_model("odoo_app", "Role")
    RolePermission = apps.get_model("odoo_app", "RolePermission")

    perms = {}
    for codename, description in NEW_PERMISSIONS.items():
        perms[codename], _ = Permission.objects.get_or_create(codename=codename, defaults={"description": description})

    for role in Role.objects.filter(name__in=["owner", *EXPORT_AREAS]):
        current = set(
            RolePermission.objects.filter(role=role).values_list("permission__codename", flat=True)
        )
        for codename in grants_for(role.name, current):
            RolePermission.objects.get_or_create(role=role, permission=perms[codename])


def backwards(apps, schema_editor):
    Permission = apps.get_model("odoo_app", "Permission")
    RolePermission = apps.get_model("odoo_app", "RolePermission")
    for codename in NEW_PERMISSIONS:
        RolePermission.objects.filter(permission__codename=codename).delete()
        Permission.objects.filter(codename=codename).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("odoo_app", "0045_chatsession_user_id"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
