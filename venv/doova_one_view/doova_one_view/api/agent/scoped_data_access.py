"""
doova_one_view/api/agent/scoped_data_access.py

ScopedDataAccess: The Architectural Choke Point for Tenant and Company Scoping.
Ensures every query builder strictly binds tenant_id and company_id/company_ids from the session context,
preventing cross-tenant data leakage by design.
"""

from typing import Optional, List, Dict, Any, Union
from django.db.models import QuerySet
from django.db import connection

from odoo_app.models.sales_order import SalesOrder
from odoo_app.models.sales_order_line import SalesOrderLine
from odoo_app.models.purchase_order import PurchaseOrder
from odoo_app.models.purchase_order_line import PurchaseOrderLine
from odoo_app.models.account_move import AccountMove
from odoo_app.models.account_move_line import AccountMoveLine
from odoo_app.models.stock_quant import StockQuant
from odoo_app.models.stock_move import StockMove
from odoo_app.models.stock_move_line import StockMoveLine
from odoo_app.models.stock_picking import StockPicking
from odoo_app.models.bank_statement import BankStatement
from odoo_app.models.bank_statement_line import BankStatementLine
from odoo_app.models.product import Product
from odoo_app.models.partner import Partner
from odoo_app.models.company import Company
from odoo_app.models.tenant import Tenant
from doova_one_view.api.agent.query_context import (
    build_tenant_filter_sql,
    build_company_filter_sql,
    normalize_company_ids,
    normalize_tenant_ids,
    apply_scope_filter_orm,
)


class ScopedDataAccess:
    """
    Unified, non-bypassable data access layer.
    Guarantees that every query strictly filters by the bound tenant_ids list
    and optional company_ids, preventing cross-tenant leakage.
    Follows the dynamic operator contract:
      len == 0 -> no filter
      len == 1 -> strict '='
      len > 1  -> set 'IN'
    """

    def __init__(
        self,
        tenant_ids: Optional[Union[List[str], str]] = None,
        company_ids: Optional[Union[List[int], str, int]] = None,
    ):
        self.tenant_ids = normalize_tenant_ids(tenant_ids)
        self.resolved_company_ids = normalize_company_ids(company_ids)
        self.tenant_id = self.tenant_ids[0] if len(self.tenant_ids) == 1 else None

    def _apply_tenant_filter(self, qs: QuerySet, field_name: str = "tenant_id") -> QuerySet:
        return apply_scope_filter_orm(qs, field_name, self.tenant_ids)

    def _apply_company_filter(self, qs: QuerySet, field_name: str = "company_id") -> QuerySet:
        return apply_scope_filter_orm(qs, field_name, self.resolved_company_ids)

    # ── Fact Tables ──────────────────────────────────────────────────────────

    def sales_orders(self) -> QuerySet[SalesOrder]:
        qs = self._apply_tenant_filter(SalesOrder.objects.all(), "tenant_id")
        return self._apply_company_filter(qs, "company_id")

    def sales_order_lines(self) -> QuerySet[SalesOrderLine]:
        qs = self._apply_tenant_filter(SalesOrderLine.objects.all(), "sales_order__tenant_id")
        qs = qs.exclude(product__product_type='service').exclude(product__name__icontains='discount')
        return self._apply_company_filter(qs, "sales_order__company_id")

    def purchase_orders(self) -> QuerySet[PurchaseOrder]:
        qs = self._apply_tenant_filter(PurchaseOrder.objects.all(), "tenant_id")
        return self._apply_company_filter(qs, "company_id")

    def purchase_order_lines(self) -> QuerySet[PurchaseOrderLine]:
        qs = self._apply_tenant_filter(PurchaseOrderLine.objects.all(), "purchase_order__tenant_id")
        return self._apply_company_filter(qs, "purchase_order__company_id")

    def account_moves(self) -> QuerySet[AccountMove]:
        qs = self._apply_tenant_filter(AccountMove.objects.all(), "tenant_id")
        return self._apply_company_filter(qs, "company_id")

    def account_move_lines(self) -> QuerySet[AccountMoveLine]:
        qs = self._apply_tenant_filter(AccountMoveLine.objects.all(), "tenant_id")
        return self._apply_company_filter(qs, "company_id")

    def stock_quants(self) -> QuerySet[StockQuant]:
        qs = self._apply_tenant_filter(StockQuant.objects.all(), "tenant_id")
        return self._apply_company_filter(qs, "company_id")

    def stock_moves(self) -> QuerySet[StockMove]:
        qs = self._apply_tenant_filter(StockMove.objects.all(), "tenant_id")
        return self._apply_company_filter(qs, "company_id")

    def stock_move_lines(self) -> QuerySet[StockMoveLine]:
        qs = self._apply_tenant_filter(StockMoveLine.objects.all(), "tenant_id")
        return self._apply_company_filter(qs, "company_id")

    def stock_pickings(self) -> QuerySet[StockPicking]:
        qs = self._apply_tenant_filter(StockPicking.objects.all(), "tenant_id")
        return self._apply_company_filter(qs, "company_id")

    def bank_statements(self) -> QuerySet[BankStatement]:
        qs = self._apply_tenant_filter(BankStatement.objects.all(), "tenant_id")
        return self._apply_company_filter(qs, "company_id")

    def bank_statement_lines(self) -> QuerySet[BankStatementLine]:
        qs = self._apply_tenant_filter(BankStatementLine.objects.all(), "statement__tenant_id")
        return self._apply_company_filter(qs, "statement__company_id")

    # ── Dimension Tables ─────────────────────────────────────────────────────

    def products(self) -> QuerySet[Product]:
        return self._apply_tenant_filter(Product.objects.all(), "tenant_id")

    def partners(self) -> QuerySet[Partner]:
        return self._apply_tenant_filter(Partner.objects.all(), "tenant_id")

    def companies(self) -> QuerySet[Company]:
        qs = self._apply_tenant_filter(Company.objects.all(), "tenant_id")
        if self.resolved_company_ids:
            qs = qs.filter(odoo_id__in=self.resolved_company_ids)
        return qs

    # ── Scoped SQL Execution ─────────────────────────────────────────────────

    def execute_scoped_sql(self, base_sql: str, table_alias: str = "", extra_params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        Executes raw SQL query while injecting the mandatory tenant and company filter conditions.
        """
        t_col = f"{table_alias}.tenant_id" if table_alias else "tenant_id"
        c_col = f"{table_alias}.company_id" if table_alias else "company_id"
        t_sql, t_params = build_tenant_filter_sql(tenant_ids=self.tenant_ids, column_name=t_col, prefix="sda_t")
        c_sql, c_params = build_company_filter_sql(company_ids=self.resolved_company_ids, column_name=c_col, prefix="sda_c")
        
        clauses = [c for c in [t_sql.strip(), c_sql.strip()] if c]
        filter_clause = " ".join(clauses)
        params = {**t_params, **c_params}

        if extra_params:
            params.update(extra_params)

        # Ensure filter_clause is present in SQL query
        if "{tenant_filter}" in base_sql:
            final_sql = base_sql.format(tenant_filter=filter_clause)
        else:
            final_sql = f"{base_sql} {filter_clause}" if filter_clause else base_sql

        with connection.cursor() as cursor:
            cursor.execute(final_sql, params)
            columns = [col[0] for col in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def resolve_tenant_name(self) -> str:
        """Resolve human-friendly tenant name or concatenated group name."""
        try:
            tenants = list(Tenant.objects.filter(id__in=self.tenant_ids))
            if len(tenants) == 1:
                return tenants[0].name
            elif len(tenants) > 1:
                return ", ".join(t.name for t in tenants)
        except Exception:
            pass
        return "Organization"
