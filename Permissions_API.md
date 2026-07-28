# Doova One View — RBAC Permissions Reference

> **Last updated:** 2026-07-27
> **Total permissions:** 42
> **Migration:** `odoo_app.0028_update_rbac_permissions`
> **Stale permissions removed by:** `odoo_app.0029_delete_stale_permissions`

---

## Overview

Permissions are enforced at the **FastAPI route level** via dependency injection using `require_permissions()` or `require_any_permission()` from `doova_one_view.api.auth.permissions`.

Every authenticated request must carry a valid JWT token. The token is resolved to a user, whose roles are looked up to produce a set of permission codenames. If the required codename is absent, the API returns **403 Forbidden**.

---

## Permission Enforcement Helpers

| Helper | Behavior |
|---|---|
| `require_permissions("codename")` | User **must** have the permission |
| `require_any_permission("a", "b")` | User must have **at least one** of the listed permissions |

---

## Permissions by Module

---

### 1. System

| Codename | Description | Guards |
|---|---|---|
| `view_kpi` | View the main dashboard & KPI overview | `GET /kpi/summary`, `GET /kpi/cards`, `GET /kpi/metric-details`, `GET /kpi/daily-moves`, `GET /kpi/market-breakdown` |
| `use_agent` | Send queries to the AI agent | `POST /agent/chat`, `GET /agent/sessions`, `GET /agent/sessions/{id}` |

---

### 2. Tenant Management

| Codename | Description | Guards |
|---|---|---|
| `view_tenants` | View the tenant list | `GET /tenants/`, `GET /tenants/{id}` |
| `manage_tenants` | Create, update, and delete tenants | `POST /tenants/`, `PATCH /tenants/{id}`, `DELETE /tenants/{id}` |

---

### 3. User & Role Management

| Codename | Description | Guards |
|---|---|---|
| `manage_users` | Create, update, and deactivate user accounts | `POST /auth/users`, `PATCH /auth/users/{id}`, `DELETE /auth/users/{id}`, `GET /auth/users` |
| `manage_roles` | Create roles, assign permissions, and assign roles to users | `GET /rbac/roles`, `POST /rbac/roles`, `PATCH /rbac/roles/{id}`, `DELETE /rbac/roles/{id}`, `POST /rbac/roles/{id}/permissions`, `POST /rbac/users/{id}/roles` |

---

### 4. Sales

| Codename | Description | Guards |
|---|---|---|
| `view_sales_overview` | View the sales executive overview dashboard | `GET /sales/overview` |
| `view_sales_orders` | View sales orders list, detail, filters, and search | `GET /sales/orders`, `GET /sales/orders/{id}`, `GET /sales/orders/{id}/lines` |
| `export_sales_orders` | Export sales orders to CSV | `GET /sales/orders/export` |

---

### 5. Purchase

| Codename | Description | Guards |
|---|---|---|
| `view_purchase_overview` | View the purchase executive overview dashboard | `GET /purchase/overview` |
| `view_purchase_orders` | View purchase orders list, detail, filters, and search | `GET /purchase/orders`, `GET /purchase/orders/{id}`, `GET /purchase/orders/{id}/lines` |
| `export_purchase_orders` | Export purchase orders to CSV | `GET /purchase/orders/export` |

---

### 6. Accounting — Moves

| Codename | Description | Guards |
|---|---|---|
| `view_accounting_overview` | View the financial accounting overview dashboard | `GET /accounting/overview` |
| `view_accounting_moves` | View journal entries and account moves | `GET /accounting/moves`, `GET /accounting/moves/{id}` |
| `export_accounting_moves` | Export accounting moves to CSV | `GET /accounting/moves/export` |

---

### 7. Bank Statements

| Codename | Description | Guards |
|---|---|---|
| `view_bank_statements` | View bank statements and their lines | `GET /bank-statements/`, `GET /bank-statements/{id}`, `GET /bank-statements/{id}/lines` |
| `export_bank_statements` | Export bank statements to CSV | `GET /bank-statements/export` |

---

### 8. Account Journals

| Codename | Description | Guards |
|---|---|---|
| `view_account_journals` | View accounting journals | `GET /account-journals/`, `GET /account-journals/{id}` |
| `export_account_journals` | Export accounting journals to CSV | `GET /account-journals/export` |

---

### 9. Account Reconciles

| Codename | Description | Guards |
|---|---|---|
| `view_account_reconciles` | View partial reconciliation records | `GET /account-reconciles/`, `GET /account-reconciles/{id}` |
| `export_account_reconciles` | Export partial reconciliation records to CSV | `GET /account-reconciles/export` |

---

### 10. Inventory — Moves

| Codename | Description | Guards |
|---|---|---|
| `view_inventory_overview` | View the stock and inventory overview dashboard | `GET /inventory/overview` |
| `view_inventory_moves` | View stock movement logs, filters, and search | `GET /inventory/moves`, `GET /inventory/moves/{id}` |
| `export_inventory_moves` | Export inventory moves to CSV | `GET /inventory/moves/export` |

---

### 11. Inventory — Pickings

| Codename | Description | Guards |
|---|---|---|
| `view_inventory_pickings` | View warehouse pickings | `GET /inventory/pickings`, `GET /inventory/pickings/{id}` |
| `export_inventory_pickings` | Export inventory pickings to CSV | `GET /inventory/pickings/export` |

---

### 12. Inventory — Quants

| Codename | Description | Guards |
|---|---|---|
| `view_inventory_quants` | View stock quantities by location | `GET /inventory/quants`, `GET /inventory/quants/{id}` |
| `export_inventory_quants` | Export inventory quants to CSV | `GET /inventory/quants/export` |

---

### 13. Master Data — Partners

| Codename | Description | Guards |
|---|---|---|
| `view_partners` | View business partners and contacts | `GET /master-data/partners`, `GET /master-data/partners/{id}` |
| `export_partners` | Export partners to CSV | `GET /master-data/partners/export` |

---

### 14. Master Data — Products

| Codename | Description | Guards |
|---|---|---|
| `view_products` | View the product catalog | `GET /master-data/products`, `GET /master-data/products/{id}` |
| `export_products` | Export products to CSV | `GET /master-data/products/export` |

---

### 15. Master Data — Lots

| Codename | Description | Guards |
|---|---|---|
| `view_lots` | View serial numbers and lot numbers | `GET /master-data/lots`, `GET /master-data/lots/{id}` |
| `export_lots` | Export lots to CSV | `GET /master-data/lots/export` |

---

### 16. Master Data — Categories & Chart of Accounts

| Codename | Description | Guards |
|---|---|---|
| `view_categories` | View product categories | `GET /master-data/categories` |
| `view_chart_of_accounts` | View chart of accounts | `GET /master-data/chart-of-accounts` |
| `export_chart_of_accounts` | Export chart of accounts to CSV | `GET /master-data/chart-of-accounts/export` |

---

### 17. Storage / Files

| Codename | Description | Guards |
|---|---|---|
| `manage_storage` | View, upload, and manage stored files | `GET /files/`, `POST /files/upload`, `DELETE /files/{id}` |

---

### 18. Reports

| Codename | Description | Guards |
|---|---|---|
| `view_reports` | View generated report history | `GET /reports/history` (also grantable via `manage_reports`) |
| `manage_reports` | Create, update, delete, and trigger report schedules | `POST /reports/schedules`, `GET /reports/schedules`, `PATCH /reports/schedules/{id}`, `DELETE /reports/schedules/{id}`, `POST /reports/schedules/{id}/send-now` |

> **Note:** `GET /reports/history` accepts either `view_reports` **or** `manage_reports`.

---

### 19. Alerts

| Codename | Description | Guards |
|---|---|---|
| `view_alerts` | View proactive anomaly alert schedules and history | `GET /alerts/history` (also grantable via `manage_alerts`) |
| `manage_alerts` | Create, update, delete, and trigger alert schedules | `POST /alerts/schedules`, `GET /alerts/schedules`, `PATCH /alerts/schedules/{id}`, `DELETE /alerts/schedules/{id}`, `POST /alerts/schedules/{id}/send-now` |

> **Note:** `GET /alerts/history` accepts either `view_alerts` **or** `manage_alerts`.

---

## Role → Permission Matrix

| Permission | owner | manager | accountant | inventory_clerk | sales_rep |
|---|:---:|:---:|:---:|:---:|:---:|
| `view_kpi` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `use_agent` | ✅ | ✅ | ✅ | | |
| `view_tenants` | ✅ | ✅ | | | |
| `manage_tenants` | ✅ | | | | |
| `manage_users` | ✅ | ✅ | | | |
| `manage_roles` | ✅ | | | | |
| `view_sales_overview` | ✅ | ✅ | ✅ | | ✅ |
| `view_sales_orders` | ✅ | ✅ | ✅ | | ✅ |
| `export_sales_orders` | ✅ | ✅ | | | ✅ |
| `view_purchase_overview` | ✅ | ✅ | ✅ | | |
| `view_purchase_orders` | ✅ | ✅ | ✅ | | |
| `export_purchase_orders` | ✅ | ✅ | | | |
| `view_accounting_overview` | ✅ | ✅ | ✅ | | |
| `view_accounting_moves` | ✅ | ✅ | ✅ | | |
| `export_accounting_moves` | ✅ | ✅ | ✅ | | |
| `view_bank_statements` | ✅ | ✅ | ✅ | | |
| `export_bank_statements` | ✅ | ✅ | ✅ | | |
| `view_account_journals` | ✅ | ✅ | ✅ | | |
| `export_account_journals` | ✅ | ✅ | ✅ | | |
| `view_account_reconciles` | ✅ | ✅ | ✅ | | |
| `export_account_reconciles` | ✅ | ✅ | ✅ | | |
| `view_inventory_overview` | ✅ | ✅ | | ✅ | |
| `view_inventory_moves` | ✅ | ✅ | | ✅ | |
| `export_inventory_moves` | ✅ | ✅ | | ✅ | |
| `view_inventory_pickings` | ✅ | ✅ | | ✅ | |
| `export_inventory_pickings` | ✅ | ✅ | | ✅ | |
| `view_inventory_quants` | ✅ | ✅ | | ✅ | |
| `export_inventory_quants` | ✅ | ✅ | | ✅ | |
| `view_partners` | ✅ | ✅ | ✅ | | ✅ |
| `export_partners` | ✅ | ✅ | | | |
| `view_products` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `export_products` | ✅ | ✅ | | | |
| `view_lots` | ✅ | ✅ | | ✅ | |
| `export_lots` | ✅ | ✅ | | | |
| `view_categories` | ✅ | ✅ | ✅ | ✅ | |
| `view_chart_of_accounts` | ✅ | ✅ | ✅ | | |
| `export_chart_of_accounts` | ✅ | ✅ | ✅ | | |
| `manage_storage` | ✅ | ✅ | | | |
| `view_reports` | ✅ | ✅ | ✅ | | |
| `manage_reports` | ✅ | ✅ | | | |
| `view_alerts` | ✅ | ✅ | | | |
| `manage_alerts` | ✅ | ✅ | | | |

---

## Default Roles Summary

| Role | Description |
|---|---|
| **owner** | Superadmin — holds all 42 permissions |
| **manager** | Operations manager — full access to all modules except tenant/role admin |
| **accountant** | Financial staff — full accounting access, read-only sales/purchase/master data |
| **inventory_clerk** | Warehouse staff — full inventory access, read-only product/lot/category data |
| **sales_rep** | Sales staff — full sales access, read-only products and partners |

---

## Adding New Permissions

1. Add the codename + description to `PERMISSIONS` in `odoo_app/migrations/0028_update_rbac_permissions.py` or a new migration.
2. Add `require_permissions("your_codename")` (or `require_any_permission(...)`) to the relevant route.
3. Assign the permission to the appropriate roles in the `ROLES` dictionary.
4. Run `python manage.py migrate`.

---

## Removing Permissions

1. Remove all `require_permissions("old_codename")` references from routes.
2. Create a new migration (see `0029_delete_stale_permissions.py` as a template) that calls `Permission.objects.filter(codename="old_codename").delete()`.
3. Remove the codename from the `PERMISSIONS` list and all `ROLES` in `0028_update_rbac_permissions.py`.
4. Run `python manage.py migrate`.
