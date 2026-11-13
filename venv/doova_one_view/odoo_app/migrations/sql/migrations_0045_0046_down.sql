-- Doova OneView: undo odoo_app migrations 0046 and 0045 (plain PostgreSQL).
-- Same result as:  python manage.py migrate odoo_app 0044
-- One transaction. Safe to run more than once.
-- Run:  psql -v ON_ERROR_STOP=1 -d <database> -f migrations_0045_0046_down.sql
-- Warning: this deletes the chat-session owner column (its data is lost) and removes the
-- 15 permissions from every role, custom roles included. Roll the backend code back first.

BEGIN;

-- ── undo 0046_restore_required_permissions ───────────────────────────────
DELETE FROM rbac_role_permissions
WHERE permission_id IN (
  SELECT id FROM rbac_permissions WHERE codename IN (
    'export_sales_orders', 'export_purchase_orders', 'export_accounting_moves',
    'export_account_journals', 'export_account_reconciles', 'export_bank_statements',
    'export_chart_of_accounts', 'export_inventory_moves', 'export_inventory_pickings',
    'export_inventory_quants', 'export_lots', 'export_partners', 'export_products',
    'manage_reports', 'manage_storage'));

DELETE FROM rbac_permissions WHERE codename IN (
  'export_sales_orders', 'export_purchase_orders', 'export_accounting_moves',
  'export_account_journals', 'export_account_reconciles', 'export_bank_statements',
  'export_chart_of_accounts', 'export_inventory_moves', 'export_inventory_pickings',
  'export_inventory_quants', 'export_lots', 'export_partners', 'export_products',
  'manage_reports', 'manage_storage');

DELETE FROM django_migrations
WHERE app = 'odoo_app' AND name = '0046_restore_required_permissions';

-- ── undo 0045_chatsession_user_id ────────────────────────────────────────
DROP INDEX IF EXISTS agent_chat_sessions_user_id_b4879983;
ALTER TABLE agent_chat_sessions DROP COLUMN IF EXISTS user_id;

DELETE FROM django_migrations
WHERE app = 'odoo_app' AND name = '0045_chatsession_user_id';

COMMIT;
