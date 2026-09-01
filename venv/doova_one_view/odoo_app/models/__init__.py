"""
odoo_app.models package
This file imports all model modules so Django can discover them.
"""
# Import submodules to register models with Django
from odoo_app.models.tenant import *
from odoo_app.models.sync_log import *
from odoo_app.models.company import *
from odoo_app.models.product_category import *
from odoo_app.models.product import *
from odoo_app.models.partner import *
from odoo_app.models.odoo_user import *
from odoo_app.models.time_dimension import *
from odoo_app.models.sales_order import *
from odoo_app.models.sales_order_line import *
from odoo_app.models.account_move import *
from odoo_app.models.account_move_line import *
from odoo_app.models.lot import *
from odoo_app.models.stock_picking import *
from odoo_app.models.stock_move import *
from odoo_app.models.stock_move_line import *
from odoo_app.models.stock_quant import *
from odoo_app.models.purchase_order import *
from odoo_app.models.purchase_order_line import *
from odoo_app.models.daily_kpi import *
from odoo_app.models.forecast import *
from odoo_app.models.anomaly import *
from odoo_app.models.app_user import *
from odoo_app.models.user_tenant_access import *
from odoo_app.models.rbac import *
from odoo_app.models.stored_file import *
from odoo_app.models.agent import *
from odoo_app.models.password_reset_otp import *
from odoo_app.models.report_schedule import *
from odoo_app.models.alert_schedule import *
from odoo_app.models.tenant_financial_mapping import *
from odoo_app.models.chart_of_accounts import *
from odoo_app.models.currency import *
from odoo_app.models.currency_rate import *
from odoo_app.models.bank_statement import *
from odoo_app.models.bank_statement_line import *
from odoo_app.models.account_journal import *
from odoo_app.models.account_partial_reconcile import *
from odoo_app.models.account_account_tag import *

__all__ = [
    'PurchaseOrderLine',
    'ChartOfAccounts',
    'AccountAccountTag',
    'BankStatement',
    'BankStatementLine',
    'AccountJournal',
    'AccountPartialReconcile',
]