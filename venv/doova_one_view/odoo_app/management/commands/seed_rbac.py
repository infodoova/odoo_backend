"""
Management command: python manage.py seed_rbac

Creates a superuser, default permissions, and default roles.
Safe to re-run — uses get_or_create everywhere.
"""

from django.core.management.base import BaseCommand
from django.contrib.auth.hashers import make_password


PERMISSIONS = [
    # Main & System
    ("view_kpi",                    "View main dashboard & KPI overview"),
    ("view_notifications",          "View system notifications"),
    ("view_settings",               "View and modify application settings"),
    ("view_support",                "Access help & customer support"),
    
    # Tenants / Admin / RBAC
    ("view_tenants",                "View tenant list"),
    ("manage_tenants",              "Create, update, and delete tenants"),
    ("view_users",                  "View user list and details"),
    ("manage_users",                "Create and deactivate users"),
    ("manage_roles",                "Create roles, assign permissions, assign roles to users"),

    # Sales
    ("view_sales",                  "View sales orders and summaries"),
    ("view_sales_overview",         "View sales executive overview"),
    ("view_sales_orders",           "View sales orders list and details"),
    ("view_sales_order_lines",      "View sales order lines"),
    ("view_sales_customers",        "View customer sales profiles"),
    ("export_sales",                "Export sales data"),

    # Purchases
    ("view_purchases",              "View purchase orders and summaries"),
    ("view_purchase_overview",      "View purchase executive overview"),
    ("view_purchase_orders",        "View purchase orders list and details"),
    ("view_purchase_order_lines",   "View purchase order lines"),
    ("export_purchases",            "Export purchase data"),

    # Accounting & Finance
    ("view_accounting",             "View financial overview and account moves"),
    ("view_accounting_overview",    "View financial accounting overview"),
    ("view_accounting_moves",       "View journal entries and account moves"),
    ("view_finance_invoices",       "View customer and vendor invoices"),
    ("view_finance_expenses",       "View business expenses"),
    ("view_finance_budget",         "View budget allocations"),
    ("view_chart_of_accounts",      "View chart of accounts"),
    ("view_bank_statements",        "View bank statements"),
    ("view_account_journals",       "View accounting journals"),
    ("view_account_reconciles",     "View partial reconciliation records"),
    ("export_accounting",           "Export accounting data"),

    # Inventory & Storage
    ("view_inventory",              "View stock and inventory levels"),
    ("view_inventory_overview",     "View stock and inventory overview"),
    ("view_inventory_moves",        "View stock movement logs"),
    ("view_inventory_pickings",     "View warehouse pickings"),
    ("view_inventory_quants",       "View stock quantities by location"),
    ("view_storage",                "View warehouse storage locations"),
    ("view_products",               "View product catalog"),
    ("view_lots",                   "View serial and lot numbers"),
    ("view_categories",             "View product categories"),
    ("export_inventory",            "Export inventory data"),

    # Master Data & Partners
    ("view_partners",               "View business partners and contacts"),
    ("view_master_data",            "View general master reference data"),

    # Analytics, Reports, Alerts, AI
    ("view_reports",                "View generated business reports"),
    ("export_reports",              "Download and export reports"),
    ("view_alerts",                 "View proactive anomaly alerts"),
    ("manage_alerts",               "Create and manage alert schedules"),
    ("use_agent",                   "Send queries to the AI agent"),

    # Permissions the API routes check (see migration 0046_restore_required_permissions)
    ("export_sales_orders",         "Export sales orders"),
    ("export_purchase_orders",      "Export purchase orders"),
    ("export_accounting_moves",     "Export journal entries and invoices"),
    ("export_account_journals",     "Export accounting journals"),
    ("export_account_reconciles",   "Export payment reconciliations"),
    ("export_bank_statements",      "Export bank statements"),
    ("export_chart_of_accounts",    "Export the chart of accounts"),
    ("export_inventory_moves",      "Export stock moves"),
    ("export_inventory_pickings",   "Export transfers (pickings)"),
    ("export_inventory_quants",     "Export stock on hand"),
    ("export_lots",                 "Export lots and serial numbers"),
    ("export_partners",             "Export customers and suppliers"),
    ("export_products",             "Export products"),
    ("manage_reports",              "Create, update, delete and send report schedules"),
    ("manage_storage",              "Upload, download and delete stored files"),
]

_ACCOUNTING_EXPORTS = [
    "export_accounting_moves", "export_account_journals", "export_account_reconciles",
    "export_bank_statements", "export_chart_of_accounts",
]
_INVENTORY_EXPORTS = ["export_inventory_moves", "export_inventory_pickings", "export_inventory_quants", "export_lots"]

ROLES = {
    "owner": [p[0] for p in PERMISSIONS],  # all permissions

    "manager": [
        "view_kpi", "view_notifications", "view_settings", "view_support",
        "view_tenants", "view_users",
        "view_sales", "view_sales_overview", "view_sales_orders", "view_sales_order_lines", "view_sales_customers", "export_sales",
        "view_purchases", "view_purchase_overview", "view_purchase_orders", "view_purchase_order_lines", "export_purchases",
        "view_accounting", "view_accounting_overview", "view_accounting_moves", "view_finance_invoices", "view_finance_expenses", "view_finance_budget", "view_chart_of_accounts", "view_bank_statements", "view_account_journals", "view_account_reconciles", "export_accounting",
        "view_inventory", "view_inventory_overview", "view_inventory_moves", "view_inventory_pickings", "view_inventory_quants", "view_storage", "view_products", "view_lots", "view_categories", "export_inventory",
        "view_partners", "view_master_data",
        "view_reports", "export_reports", "view_alerts", "manage_alerts", "use_agent",
        "export_sales_orders", "export_purchase_orders", *_ACCOUNTING_EXPORTS, *_INVENTORY_EXPORTS,
        "export_partners", "export_products", "manage_reports", "manage_storage",
    ],

    "accountant": [
        "view_kpi", "view_notifications", "view_support",
        "view_sales", "view_sales_overview", "view_sales_orders", "view_sales_order_lines", "view_sales_customers",
        "view_purchases", "view_purchase_overview", "view_purchase_orders", "view_purchase_order_lines",
        "view_accounting", "view_accounting_overview", "view_accounting_moves", "view_finance_invoices", "view_finance_expenses", "view_finance_budget", "view_chart_of_accounts", "view_bank_statements", "view_account_journals", "view_account_reconciles", "export_accounting",
        "view_inventory", "view_products", "view_categories",
        "view_partners", "view_master_data",
        "view_reports", "export_reports", "view_alerts", "use_agent",
        *_ACCOUNTING_EXPORTS, "export_partners",
    ],

    "inventory_clerk": [
        "view_kpi", "view_notifications", "view_support",
        "view_inventory", "view_inventory_overview", "view_inventory_moves", "view_inventory_pickings", "view_inventory_quants", "view_storage", "view_products", "view_lots", "view_categories", "export_inventory",
        "view_master_data",
        *_INVENTORY_EXPORTS, "export_products", "manage_storage",
    ],

    "sales_rep": [
        "view_kpi", "view_notifications", "view_support",
        "view_sales", "view_sales_overview", "view_sales_orders", "view_sales_order_lines", "view_sales_customers", "export_sales",
        "view_products", "view_partners", "view_master_data",
        "export_sales_orders", "export_partners", "export_products",
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
