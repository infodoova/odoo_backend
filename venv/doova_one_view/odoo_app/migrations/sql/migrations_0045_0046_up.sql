-- Doova OneView: odoo_app migrations 0045 and 0046 as plain PostgreSQL (13 or newer).
-- Same result as:  python manage.py migrate odoo_app 0046
-- One transaction (all or nothing). Safe to run more than once.
-- Run:  psql -v ON_ERROR_STOP=1 -d <database> -f migrations_0045_0046_up.sql
-- Run it BEFORE starting the new backend code: that code reads agent_chat_sessions.user_id.

BEGIN;

-- Stop if this database is not at odoo_app migration 0044 or later.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM django_migrations
                 WHERE app = 'odoo_app' AND name = '0044_add_active_scope_to_chatsession') THEN
    RAISE EXCEPTION 'odoo_app migration 0044 is not applied on this database. Run "manage.py migrate" instead.';
  END IF;
END $$;


-- ── 0045_chatsession_user_id ─────────────────────────────────────────────
-- Stores which user owns each chat session (used by the session ownership checks).
ALTER TABLE agent_chat_sessions ADD COLUMN IF NOT EXISTS user_id uuid NULL;
CREATE INDEX IF NOT EXISTS agent_chat_sessions_user_id_b4879983 ON agent_chat_sessions (user_id);

INSERT INTO django_migrations (app, name, applied)
SELECT 'odoo_app', '0045_chatsession_user_id', now()
WHERE NOT EXISTS (SELECT 1 FROM django_migrations
                  WHERE app = 'odoo_app' AND name = '0045_chatsession_user_id');


-- ── 0046_restore_required_permissions ────────────────────────────────────
-- Creates the 15 permissions the API checks but the database never had, and grants them
-- to the built-in roles. Custom roles are not touched.
DROP TABLE IF EXISTS pg_temp._perms_0046;
CREATE TEMP TABLE _perms_0046 (
  codename    varchar(100) PRIMARY KEY,
  description varchar(255) NOT NULL
) ON COMMIT DROP;

INSERT INTO _perms_0046 (codename, description) VALUES
  ('export_sales_orders',       'Export sales orders'),
  ('export_purchase_orders',    'Export purchase orders'),
  ('export_accounting_moves',   'Export journal entries and invoices'),
  ('export_account_journals',   'Export accounting journals'),
  ('export_account_reconciles', 'Export payment reconciliations'),
  ('export_bank_statements',    'Export bank statements'),
  ('export_chart_of_accounts',  'Export the chart of accounts'),
  ('export_inventory_moves',    'Export stock moves'),
  ('export_inventory_pickings', 'Export transfers (pickings)'),
  ('export_inventory_quants',   'Export stock on hand'),
  ('export_lots',               'Export lots and serial numbers'),
  ('export_partners',           'Export customers and suppliers'),
  ('export_products',           'Export products'),
  ('manage_reports',            'Create, update, delete and send report schedules'),
  ('manage_storage',            'Upload, download and delete stored files');

INSERT INTO rbac_permissions (id, codename, description, created_at)
SELECT gen_random_uuid(), codename, description, now()
FROM _perms_0046
ON CONFLICT (codename) DO NOTHING;

-- Grant rules:
--   owner            -> all 15
--   an export        -> only to a role that could already export that business area
--                       AND already has the matching view permission
--   manage_reports   -> manager
--   manage_storage   -> manager, inventory_clerk
WITH export_rules (codename, area, view_perm) AS (VALUES
  ('export_sales_orders',       'sales',      'view_sales_orders'),
  ('export_purchase_orders',    'purchases',  'view_purchase_orders'),
  ('export_accounting_moves',   'accounting', 'view_accounting_moves'),
  ('export_account_journals',   'accounting', 'view_account_journals'),
  ('export_account_reconciles', 'accounting', 'view_account_reconciles'),
  ('export_bank_statements',    'accounting', 'view_bank_statements'),
  ('export_chart_of_accounts',  'accounting', 'view_chart_of_accounts'),
  ('export_inventory_moves',    'inventory',  'view_inventory_moves'),
  ('export_inventory_pickings', 'inventory',  'view_inventory_pickings'),
  ('export_inventory_quants',   'inventory',  'view_inventory_quants'),
  ('export_lots',               'inventory',  'view_lots'),
  ('export_partners',           'sales',      'view_partners'),
  ('export_partners',           'purchases',  'view_partners'),
  ('export_partners',           'accounting', 'view_partners'),
  ('export_products',           'sales',      'view_products'),
  ('export_products',           'purchases',  'view_products'),
  ('export_products',           'inventory',  'view_products')
),
role_areas (role_name, area) AS (VALUES
  ('manager', 'sales'), ('manager', 'purchases'), ('manager', 'accounting'), ('manager', 'inventory'),
  ('accountant', 'accounting'),
  ('inventory_clerk', 'inventory'),
  ('sales_rep', 'sales')
),
role_has (role_id, codename) AS (
  SELECT rp.role_id, p.codename
  FROM rbac_role_permissions rp
  JOIN rbac_permissions p ON p.id = rp.permission_id
),
grants (role_id, codename) AS (
  SELECT r.id, n.codename::text
  FROM rbac_roles r CROSS JOIN _perms_0046 n
  WHERE r.name = 'owner'
  UNION
  SELECT r.id, er.codename
  FROM rbac_roles r
  JOIN role_areas   ra ON ra.role_name = r.name
  JOIN export_rules er ON er.area = ra.area
  JOIN role_has     h  ON h.role_id = r.id AND h.codename = er.view_perm
  UNION
  SELECT r.id, 'manage_reports' FROM rbac_roles r WHERE r.name = 'manager'
  UNION
  SELECT r.id, 'manage_storage' FROM rbac_roles r WHERE r.name IN ('manager', 'inventory_clerk')
)
INSERT INTO rbac_role_permissions (role_id, permission_id, assigned_at)
SELECT g.role_id, p.id, now()
FROM grants g
JOIN rbac_permissions p ON p.codename = g.codename
ON CONFLICT (role_id, permission_id) DO NOTHING;

INSERT INTO django_migrations (app, name, applied)
SELECT 'odoo_app', '0046_restore_required_permissions', now()
WHERE NOT EXISTS (SELECT 1 FROM django_migrations
                  WHERE app = 'odoo_app' AND name = '0046_restore_required_permissions');

COMMIT;

-- Check afterwards (owner should list all 15):
-- SELECT r.name, count(*) AS new_perms, string_agg(p.codename, ', ' ORDER BY p.codename)
-- FROM rbac_role_permissions rp
-- JOIN rbac_roles r ON r.id = rp.role_id
-- JOIN rbac_permissions p ON p.id = rp.permission_id
-- WHERE p.codename IN ('export_sales_orders', 'export_purchase_orders', 'export_accounting_moves',
--   'export_account_journals', 'export_account_reconciles', 'export_bank_statements',
--   'export_chart_of_accounts', 'export_inventory_moves', 'export_inventory_pickings',
--   'export_inventory_quants', 'export_lots', 'export_partners', 'export_products',
--   'manage_reports', 'manage_storage')
-- GROUP BY r.name ORDER BY r.name;
