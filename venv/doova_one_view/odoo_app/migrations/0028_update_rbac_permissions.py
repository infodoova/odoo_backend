from django.db import migrations


def seed_granular_permissions(apps, schema_editor):
    Permission = apps.get_model('odoo_app', 'Permission')
    Role = apps.get_model('odoo_app', 'Role')
    RolePermission = apps.get_model('odoo_app', 'RolePermission')

    # ── Complete permission list derived from all route files ──────────────────
    PERMISSIONS = [
        # ── System / Cross-cutting ──────────────────────────────────────────
        ("view_kpi",                       "View main dashboard & KPI overview"),
        ("use_agent",                      "Send queries to the AI agent"),

        # ── Tenant management ───────────────────────────────────────────────
        ("view_tenants",                   "View tenant list"),
        ("manage_tenants",                 "Create, update, and delete tenants"),

        # ── User & Role management ──────────────────────────────────────────
        ("manage_users",                   "Create and deactivate users"),
        ("manage_roles",                   "Create roles, assign permissions, assign roles to users"),

        # ── Sales ───────────────────────────────────────────────────────────
        ("view_sales_overview",            "View sales executive overview & dashboard"),
        ("view_sales_orders",              "View sales orders list, detail, filters, and search"),
        ("export_sales_orders",            "Export sales orders to CSV"),

        # ── Purchase ────────────────────────────────────────────────────────
        ("view_purchase_overview",         "View purchase executive overview & dashboard"),
        ("view_purchase_orders",           "View purchase orders list, detail, filters, and search"),
        ("export_purchase_orders",         "Export purchase orders to CSV"),

        # ── Accounting ──────────────────────────────────────────────────────
        ("view_accounting_overview",       "View financial accounting overview & dashboard"),
        ("view_accounting_moves",          "View journal entries and account moves"),
        ("export_accounting_moves",        "Export accounting moves to CSV"),

        # ── Bank Statements ─────────────────────────────────────────────────
        ("view_bank_statements",           "View bank statements"),
        ("export_bank_statements",         "Export bank statements to CSV"),

        # ── Account Journals ────────────────────────────────────────────────
        ("view_account_journals",          "View accounting journals"),
        ("export_account_journals",        "Export accounting journals to CSV"),

        # ── Account Reconciles ──────────────────────────────────────────────
        ("view_account_reconciles",        "View partial reconciliation records"),
        ("export_account_reconciles",      "Export partial reconciliation records"),

        # ── Inventory ───────────────────────────────────────────────────────
        ("view_inventory_overview",        "View stock and inventory overview & dashboard"),
        ("view_inventory_moves",           "View stock movement logs, filters, and search"),
        ("view_inventory_pickings",        "View warehouse pickings"),
        ("view_inventory_quants",          "View stock quantities by location"),
        ("export_inventory_moves",         "Export inventory moves to CSV"),
        ("export_inventory_pickings",      "Export inventory pickings to CSV"),
        ("export_inventory_quants",        "Export inventory quants to CSV"),

        # ── Master Data ─────────────────────────────────────────────────────
        ("view_partners",                  "View business partners and contacts"),
        ("export_partners",                "Export partners to CSV"),
        ("view_products",                  "View product catalog"),
        ("export_products",                "Export products to CSV"),
        ("view_lots",                      "View serial and lot numbers"),
        ("export_lots",                    "Export lots to CSV"),
        ("view_categories",                "View product categories"),
        ("view_chart_of_accounts",         "View chart of accounts"),
        ("export_chart_of_accounts",       "Export chart of accounts to CSV"),

        # ── Storage / Files ─────────────────────────────────────────────────
        ("manage_storage",                 "View, upload, and manage stored files"),

        # ── Reports ─────────────────────────────────────────────────────────
        ("view_reports",                   "View generated business reports and history"),
        ("manage_reports",                 "Create, update, delete, and trigger report schedules"),

        # ── Alerts ──────────────────────────────────────────────────────────
        ("view_alerts",                    "View proactive anomaly alert schedules and history"),
        ("manage_alerts",                  "Create, update, delete, and trigger alert schedules"),
    ]

    for codename, description in PERMISSIONS:
        Permission.objects.get_or_create(
            codename=codename,
            defaults={'description': description}
        )

    # ── Role definitions ───────────────────────────────────────────────────────
    ROLES = {
        "owner": [p[0] for p in PERMISSIONS],

        "manager": [
            # System
            "view_kpi", "use_agent",
            # Tenants & Users
            "view_tenants",
            # Sales
            "view_sales_overview", "view_sales_orders", "export_sales_orders",
            # Purchase
            "view_purchase_overview", "view_purchase_orders", "export_purchase_orders",
            # Accounting
            "view_accounting_overview", "view_accounting_moves", "export_accounting_moves",
            "view_bank_statements", "export_bank_statements",
            "view_account_journals", "export_account_journals",
            "view_account_reconciles", "export_account_reconciles",
            # Inventory
            "view_inventory_overview", "view_inventory_moves", "view_inventory_pickings",
            "view_inventory_quants", "export_inventory_moves", "export_inventory_pickings", "export_inventory_quants",
            # Master Data
            "view_partners", "export_partners",
            "view_products", "export_products",
            "view_lots", "export_lots",
            "view_categories",
            "view_chart_of_accounts", "export_chart_of_accounts",
            # Storage
            "manage_storage",
            # Reports & Alerts
            "view_reports", "manage_reports",
            "view_alerts", "manage_alerts",
        ],

        "accountant": [
            # System
            "view_kpi", "use_agent",
            # Sales (read-only)
            "view_sales_overview", "view_sales_orders",
            # Purchase (read-only)
            "view_purchase_overview", "view_purchase_orders",
            # Accounting (full)
            "view_accounting_overview", "view_accounting_moves", "export_accounting_moves",
            "view_bank_statements", "export_bank_statements",
            "view_account_journals", "export_account_journals",
            "view_account_reconciles", "export_account_reconciles",
            # Master Data (read-only)
            "view_products", "view_categories",
            "view_partners",
            "view_chart_of_accounts", "export_chart_of_accounts",
            # Reports
            "view_reports",
        ],

        "inventory_clerk": [
            # System
            "view_kpi",
            # Inventory (full)
            "view_inventory_overview", "view_inventory_moves", "view_inventory_pickings",
            "view_inventory_quants", "export_inventory_moves", "export_inventory_pickings", "export_inventory_quants",
            # Master Data (read-only)
            "view_products", "view_lots", "view_categories",
        ],

        "sales_rep": [
            # System
            "view_kpi",
            # Sales (full)
            "view_sales_overview", "view_sales_orders", "export_sales_orders",
            # Master Data (read-only)
            "view_products", "view_partners",
        ],
    }

    for role_name, perm_codenames in ROLES.items():
        role, _ = Role.objects.get_or_create(
            name=role_name,
            defaults={'description': role_name.replace('_', ' ').capitalize()}
        )
        for codename in perm_codenames:
            try:
                perm = Permission.objects.get(codename=codename)
                RolePermission.objects.get_or_create(role=role, permission=perm)
            except Permission.DoesNotExist:
                pass


def reverse_func(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('odoo_app', '0027_alertschedule_tenants_reportschedule_tenants_and_more'),
    ]

    operations = [
        migrations.RunPython(seed_granular_permissions, reverse_func),
    ]
