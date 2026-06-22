"""
Management command: python manage.py seed_rbac

Creates a superuser, default permissions, and default roles.
Safe to re-run — uses get_or_create everywhere.
"""

from django.core.management.base import BaseCommand
from django.contrib.auth.hashers import make_password


PERMISSIONS = [
    # Tenants
    ("view_tenants",        "View tenants"),
    ("manage_tenants",      "Create, update, delete tenants"),
    # Users / RBAC
    ("view_users",          "View user list"),
    ("manage_users",        "Create and deactivate users"),
    ("manage_roles",        "Create roles, assign permissions, assign roles to users"),
    # Sales
    ("view_sales",          "View sales orders and summaries"),
    ("export_sales",        "Export sales data"),
    # Purchases
    ("view_purchases",      "View purchase orders"),
    ("export_purchases",    "Export purchase data"),
    # Accounting
    ("view_accounting",     "View journal entries and account moves"),
    ("export_accounting",   "Export accounting data"),
    # Inventory
    ("view_inventory",      "View stock and inventory"),
    ("export_inventory",    "Export inventory data"),
    # KPI
    ("view_kpi",            "View KPI dashboards"),
    # Reports / Files
    ("view_reports",        "View generated reports"),
    ("export_reports",      "Download and export reports"),
    # AI Agent
    ("use_agent",           "Send queries to the AI agent"),
    # Master data
    ("view_master_data",    "View partners, products, companies"),
]

ROLES = {
    "owner": [p[0] for p in PERMISSIONS],  # all permissions

    "manager": [
        "view_tenants",
        "view_users",
        "view_sales", "export_sales",
        "view_purchases", "export_purchases",
        "view_accounting", "export_accounting",
        "view_inventory", "export_inventory",
        "view_kpi",
        "view_reports", "export_reports",
        "use_agent",
        "view_master_data",
    ],

    "accountant": [
        "view_sales",
        "view_purchases",
        "view_accounting", "export_accounting",
        "view_inventory",
        "view_kpi",
        "view_reports",
        "use_agent",
        "view_master_data",
    ],
}


class Command(BaseCommand):
    help = "Seed default permissions, roles, and optionally a superuser."

    def add_arguments(self, parser):
        parser.add_argument("--email",    default="admin@doova.com", help="Superuser email")
        parser.add_argument("--password", default="Admin@1234",       help="Superuser password")
        parser.add_argument("--name",     default="Super Admin",      help="Superuser full name")
        parser.add_argument("--no-user",  action="store_true",        help="Skip superuser creation")

    def handle(self, *args, **options):
        from odoo_app.models.app_user import AppUser
        from odoo_app.models.rbac import Permission, Role, RolePermission

        self.stdout.write("\n--- Seeding permissions ---")
        for codename, description in PERMISSIONS:
            perm, created = Permission.objects.get_or_create(
                codename=codename,
                defaults={"description": description},
            )
            status = "created" if created else "exists "
            self.stdout.write(f"  [{status}] {codename}")

        self.stdout.write("\n--- Seeding roles ---")
        for role_name, perm_codenames in ROLES.items():
            role, created = Role.objects.get_or_create(
                name=role_name,
                defaults={"description": role_name.capitalize()},
            )
            status = "created" if created else "exists "
            self.stdout.write(f"  [{status}] {role_name}")

            for codename in perm_codenames:
                try:
                    perm = Permission.objects.get(codename=codename)
                    RolePermission.objects.get_or_create(role=role, permission=perm)
                except Permission.DoesNotExist:
                    self.stderr.write(f"    WARNING: permission '{codename}' not found — skipped")

        if not options["no_user"]:
            self.stdout.write("\n--- Superuser ---")
            email = options["email"]
            user, created = AppUser.objects.get_or_create(
                email=email,
                defaults={
                    "password_hash": make_password(options["password"]),
                    "full_name": options["name"],
                    "is_active": True,
                    "is_superuser": True,
                },
            )
            if created:
                self.stdout.write(self.style.SUCCESS(f"  [created] superuser: {email}"))
            else:
                if not user.is_superuser:
                    user.is_superuser = True
                    user.save(update_fields=["is_superuser"])
                    self.stdout.write(f"  [updated] promoted existing user to superuser: {email}")
                else:
                    self.stdout.write(f"  [exists ] superuser already exists: {email}")

        self.stdout.write(self.style.SUCCESS("\nDone.\n"))
