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
from odoo_app.models.stored_file import *
from odoo_app.models.agent import *

