"""
Accounting API schemas
"""

from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing import Any, Optional, List, Union
from datetime import datetime, date
from doova_one_view.api.common.schemas import (
    PartnerRead, CompanyRead, ProductRead, PaginatedResponse
)


class AccountMoveLineRead(BaseModel):
    """Account move line schema"""
    id: int
    odoo_id: int
    product: Optional[ProductRead] = None
    account_code: Optional[str]
    account_name: Optional[str]
    debit: float
    credit: float
    balance: float
    quantity: float
    price_unit: float
    price_subtotal: float
    name: Optional[str]
    
    model_config = ConfigDict(from_attributes=True)


class AccountMoveRead(BaseModel):
    """Account move schema"""
    id: int
    odoo_id: int
    odoo_name: Optional[str]
    partner: Optional[PartnerRead] = None
    company: Optional[CompanyRead] = None
    date: date
    invoice_date: Optional[date]
    invoice_date_due: Optional[date]
    move_type: str
    state: str
    payment_state: Optional[str]
    amount_untaxed: float
    amount_tax: float
    amount_total: float
    amount_residual: float
    currency_code: Optional[str]
    ref: Optional[str]
    synced_at: datetime
    
    model_config = ConfigDict(from_attributes=True)


class AccountMoveWithLinesRead(AccountMoveRead):
    """Account move with lines"""
    lines: List[AccountMoveLineRead]

    @field_validator('lines', mode='before')
    @classmethod
    def convert_django_manager(cls, v):
        if hasattr(v, 'all'):
            return list(v.all())
        return v


class AccountingSummary(BaseModel):
    """Accounting summary dashboard schema"""
    total_invoiced: float
    total_bills: float
    total_receivable: float
    total_payable: float
    net_profit_estimate: float


class SearchFilter(BaseModel):
    """Filter criteria for advanced accounting search."""
    field: str
    operator: str
    value: Union[str, int, float, List[Any], None] = None
    maxValue: Union[str, int, float, None] = None
    max_value: Union[str, int, float, None] = None


class SearchRequest(BaseModel):
    """Advanced search request."""
    filters: List[SearchFilter] = Field(default_factory=list)
    limit: int = Field(50, ge=1, le=500)
    offset: int = Field(0, ge=0)
    company_id: Optional[int] = None
    companies: Optional[Union[str, int, List[Union[str, int]]]] = None


# ---------------------------------------------------------------------------
# Today's Expenses response schemas
# ---------------------------------------------------------------------------

class ExpenseProduct(BaseModel):
    """Product details on an expense line."""
    id: Optional[int] = None
    odoo_id: Optional[int] = None
    name: Optional[str] = None
    display_name: Optional[str] = None
    default_code: Optional[str] = None
    barcode: Optional[str] = None
    product_type: Optional[str] = None
    list_price: Optional[float] = None
    standard_price: Optional[float] = None
    uom_name: Optional[str] = None


class ExpensePartner(BaseModel):
    """Partner (vendor) details on an expense line."""
    id: Optional[int] = None
    odoo_id: Optional[int] = None
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    country_code: Optional[str] = None
    city: Optional[str] = None
    is_customer: bool = False
    is_supplier: bool = False


class ExpenseCompany(BaseModel):
    """Company details on an expense line."""
    id: Optional[int] = None
    odoo_id: Optional[int] = None
    name: Optional[str] = None
    currency_code: Optional[str] = None
    country_code: Optional[str] = None


class ExpenseLineItem(BaseModel):
    """A single line within a vendor bill expense."""
    id: int = Field(..., description="Internal database ID of the line")
    odoo_id: int = Field(..., description="Odoo source ID of the line")
    account_id: Optional[int] = Field(None, description="Account ID (if available)")
    account_name: Optional[str] = Field(None, description="Expense account name, e.g. 'Travel Expense'")
    account_code: Optional[str] = Field(None, description="Expense account code, e.g. '6301'")
    account_type: Optional[str] = Field(None, description="Account type, e.g. 'expense'")
    name: Optional[str] = Field(None, description="Line description / product name")
    quantity: float = Field(0.0, description="Quantity of the item")
    price_unit: float = Field(0.0, description="Unit price")
    price_subtotal: float = Field(0.0, description="Line subtotal (qty × unit price)")
    price_total: float = Field(0.0, description="Same as price_subtotal")
    debit: float = Field(0.0, description="Debit amount in accounting entry")
    credit: float = Field(0.0, description="Credit amount in accounting entry")
    balance: float = Field(0.0, description="Net balance (debit - credit)")
    amount_currency: float = Field(0.0, description="Amount in the document's currency")
    currency: Optional[str] = Field(None, description="Currency code")
    currency_code: Optional[str] = Field(None, description="Currency code (alias)")
    product: Optional[ExpenseProduct] = Field(None, description="Linked product, if any")
    product_id: Optional[int] = None
    product_name: Optional[str] = None
    partner: Optional[ExpensePartner] = Field(None, description="Linked partner/vendor, if any")
    partner_id: Optional[int] = None
    partner_name: Optional[str] = None
    company: Optional[ExpenseCompany] = Field(None, description="Company this line belongs to")
    company_id: Optional[int] = None
    company_name: Optional[str] = None
    synced_at: Optional[str] = Field(None, description="Last sync timestamp (ISO datetime)")


class ExpenseItem(BaseModel):
    """A single vendor bill (expense) with its line items."""
    id: int = Field(..., description="Internal database ID of the invoice")
    odoo_id: int = Field(..., description="Odoo source ID of the invoice")
    name: str = Field(..., description="Invoice reference, e.g. 'BILL/2026/07/0042'")
    amount: float = Field(..., description="Total invoice amount")
    source: str = Field(..., description="Vendor name, e.g. 'Office Depot'")
    categories: List[str] = Field(
        default_factory=list,
        description="List of expense account names from the invoice lines"
    )
    category_summary: str = Field(
        ...,
        description="Categories joined as a comma-separated string, e.g. 'Travel Expense, Utilities'"
    )
    date: Optional[str] = Field(None, description="Invoice date (YYYY-MM-DD)")
    time: Optional[str] = Field(None, description="Last sync timestamp (ISO datetime)")
    lines: List[ExpenseLineItem] = Field(
        default_factory=list,
        description="Full line-item breakdown of this invoice"
    )


class TenantExpenses(BaseModel):
    """Expenses for a single tenant."""
    tenant_id: str = Field(..., description="UUID of the tenant")
    tenant_name: str = Field(..., description="Display name of the tenant")
    date: Optional[str] = Field(None, description="The queried date (YYYY-MM-DD)")
    total_count: int = Field(..., description="Number of expense invoices for this tenant")
    total_amount: float = Field(..., description="Sum of all expense amounts for this tenant")
    items: List[ExpenseItem] = Field(
        default_factory=list,
        description="Individual expense invoices for this tenant"
    )


class AllTenantsExpensesResponse(BaseModel):
    """Full response of today's expenses across all user tenants."""
    date: Optional[str] = Field(None, description="The queried date (YYYY-MM-DD)")
    grand_total_count: int = Field(..., description="Total expense invoices across all tenants")
    grand_total_amount: float = Field(..., description="Total expense amount across all tenants")
    tenants: List[TenantExpenses] = Field(
        default_factory=list,
        description="Per-tenant expense breakdown. Each entry contains that tenant's invoices."
    )


# ---------------------------------------------------------------------------
# Revenues & Profits response schemas
# ---------------------------------------------------------------------------

class TenantRevenues(BaseModel):
    """Revenues for a single tenant."""
    tenant_id: str = Field(..., description="UUID of the tenant")
    tenant_name: str = Field(..., description="Display name of the tenant")
    date: Optional[str] = Field(None, description="The queried date (YYYY-MM-DD)")
    total_count: int = Field(..., description="Number of revenue invoices for this tenant")
    total_amount: float = Field(..., description="Sum of all revenue amounts for this tenant")
    items: List[ExpenseItem] = Field(
        default_factory=list,
        description="Individual revenue invoices for this tenant"
    )


class AllTenantsRevenuesResponse(BaseModel):
    """Full response of revenues across all user tenants."""
    date: Optional[str] = Field(None, description="The queried date (YYYY-MM-DD)")
    grand_total_count: int = Field(..., description="Total revenue invoices across all tenants")
    grand_total_amount: float = Field(..., description="Total revenue amount across all tenants")
    tenants: List[TenantRevenues] = Field(
        default_factory=list,
        description="Per-tenant revenue breakdown"
    )


class TenantProfits(BaseModel):
    """Profits (revenues & expenses combined) for a single tenant."""
    tenant_id: str = Field(..., description="UUID of the tenant")
    tenant_name: str = Field(..., description="Display name of the tenant")
    date: Optional[str] = Field(None, description="The queried date (YYYY-MM-DD)")
    total_count: int = Field(..., description="Total number of items (invoices & bills) for this tenant")
    revenue_count: int = Field(..., description="Number of revenue invoices for this tenant")
    expense_count: int = Field(..., description="Number of expense bills for this tenant")
    revenue_amount: float = Field(..., description="Total revenue amount for this tenant")
    expense_amount: float = Field(..., description="Total expense amount for this tenant")
    net_profit: float = Field(..., description="Net profit (revenue - expense) for this tenant")
    items: List[ExpenseItem] = Field(
        default_factory=list,
        description="Individual invoices & bills contributing to this profit"
    )


class AllTenantsProfitsResponse(BaseModel):
    """Full response of profits across all user tenants."""
    date: Optional[str] = Field(None, description="The queried date (YYYY-MM-DD)")
    grand_revenue_amount: float = Field(..., description="Grand total revenue across all tenants")
    grand_expense_amount: float = Field(..., description="Grand total expenses across all tenants")
    grand_net_profit: float = Field(..., description="Grand net profit across all tenants")
    grand_total_count: int = Field(..., description="Total number of transactions across all tenants")
    tenants: List[TenantProfits] = Field(
        default_factory=list,
        description="Per-tenant profit breakdown"
    )


# ── Drill-Down Schemas ──────────────────────────────────────────────────────────

class AccountingDetailMove(BaseModel):
    id: int
    odoo_id: int
    odoo_name: Optional[str]
    company_id: Optional[int] = None
    company_name: Optional[str] = None
    partner: Optional[PartnerRead] = None
    date: date
    state: str
    payment_state: Optional[str] = None
    move_type: str
    amount_total: float
    amount_residual: float
    currency_code: Optional[str]
    lines: List[AccountMoveLineRead]
    converted_amount: float
    converted_residual: float
    ref: Optional[str] = None
    synced_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MetricDetailCompanyGroup(BaseModel):
    company_id: Optional[int]
    company_name: str
    metric_value: float


class MetricDetailResponse(BaseModel):
    metric_name: str
    base_currency: str
    total_metric_value: float
    company_groups: List[MetricDetailCompanyGroup]
    items: List[AccountingDetailMove]
    total: int
    limit: int
    offset: int


class DailyMovesResponse(BaseModel):
    date: str
    base_currency: str
    total_revenue: float
    total_expenses: float
    net_profit: float
    move_count: int
    company_groups: List[MetricDetailCompanyGroup]
    items: List[AccountingDetailMove]
    total: int
    limit: int
    offset: int


class MarketBreakdownResponse(BaseModel):
    section: str
    entity_id: int
    entity_name: str
    base_currency: str
    total_amount: float
    move_count: int
    company_groups: List[MetricDetailCompanyGroup]
    items: List[AccountingDetailMove]
    total: int
    limit: int
    offset: int


class ProductMovesDetailResponse(BaseModel):
    product_id: int
    product_name: str
    product_sku: Optional[str] = None
    product_type: Optional[str] = None
    list_price: Optional[float] = None
    base_currency: str
    total_amount: float
    total_qty: float
    line_count: int
    company_groups: List[MetricDetailCompanyGroup]
    items: List[AccountMoveLineRead]
    total: int
    limit: int
    offset: int


class EntityProfileResponse(BaseModel):
    entity_id: int
    entity_type: str
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    city: Optional[str] = None


