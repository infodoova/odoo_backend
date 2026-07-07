from typing import Any, Optional, List

from pydantic import BaseModel, Field


# ── Currency Exposure & FX Impact ──────────────────────────────────────────────

class ExchangeRateItem(BaseModel):
    currency: str
    rate: float
    inverse_rate: float


class CurrencyBreakdown(BaseModel):
    currency: str
    revenue: float
    percentage: float


class CurrencyExposureResponse(BaseModel):
    base_currency: str
    currencies: List[CurrencyBreakdown] = Field(default_factory=list)
    exchange_rates: List[ExchangeRateItem] = Field(default_factory=list)
    unrealized_fx_impact: float = 0.0
    realized_fx_impact: float = 0.0
    last_updated: Optional[str] = None


class KPIMetric(BaseModel):
    value: float
    previous_value: float
    change_pct: float
    change_percentage: float


class TimeSeriesPoint(BaseModel):
    date: str
    value: float


class ProductPerformance(BaseModel):
    id: int
    name: str
    revenue: float
    quantity: float
    margin_pct: float


class CustomerPerformance(BaseModel):
    id: int
    name: str
    revenue: float
    orders: int


class OverviewResponse(BaseModel):
    kpis: dict[str, Any]
    tenant_benchmarks: list[dict[str, Any]] = Field(default_factory=list)
    applied_filters: dict[str, Any] = Field(default_factory=dict)


class KPILineItem(BaseModel):
    id: int
    odoo_id: int
    product_id: Optional[int] = None
    product_name: str
    product_code: str
    quantity: float
    qty_delivered: Optional[float] = None
    qty_received: Optional[float] = None
    qty_invoiced: float
    price_unit: float
    price_subtotal: float
    price_total: float
    discount: Optional[float] = None
    margin: Optional[float] = None
    purchase_price: Optional[float] = None
    description: Optional[str] = None
    date_planned: Optional[str] = None


class KPIOrder(BaseModel):
    id: int
    odoo_id: int
    name: str
    amount: float
    amount_total: float
    amount_untaxed: float
    amount_tax: float
    source: str
    partner_name: str
    company_name: str
    tenant_id: str
    tenant_name: str
    categories: list[str]
    category_summary: str
    date: Optional[str] = None
    time: Optional[str] = None
    state: str
    invoice_status: str
    currency_code: str
    type: str
    line_count: int
    lines: list[KPILineItem] = Field(default_factory=list)


class KPITenantSummary(BaseModel):
    tenant_id: str
    tenant_name: str
    revenue_amount: float
    expense_amount: float
    net_profit: float
    total_count: int
    revenue_count: int
    expense_count: int


class KPIPeriodDetailResponse(BaseModel):
    period: str
    kind: str
    date: str
    limit: int
    offset: int
    grand_revenue_amount: float
    grand_expense_amount: float
    grand_net_profit: float
    grand_total_count: int
    revenue_count: int
    expense_count: int
    items: list[KPIOrder] = Field(default_factory=list)
    revenues: list[KPIOrder] = Field(default_factory=list)
    expenses: list[KPIOrder] = Field(default_factory=list)
    tenants: list[KPITenantSummary] = Field(default_factory=list)


# ── Receivables Aging Detail ───────────────────────────────────────────────────

class AgingClientDetail(BaseModel):
    id: Optional[int] = None
    name: str
    email: str = ""
    phone: str = ""
    mobile: str = ""
    street: str = ""
    city: str = ""
    country: str = ""


class AgingInvoiceItem(BaseModel):
    id: int
    odoo_id: int
    invoice_number: str
    invoice_reference: str
    invoice_origin: str
    # Amounts
    amount_total: float
    amount_untaxed: float
    amount_tax: float
    amount_residual: float
    currency_code: str
    # Dates
    invoice_date: Optional[str] = None
    invoice_date_due: Optional[str] = None
    days_overdue: int
    payment_state: str
    # Client & company
    client: AgingClientDetail
    partner_name: str
    company_name: str
    tenant_id: str
    tenant_name: str


class TenantAgingDetail(BaseModel):
    tenant_id: str
    tenant_name: str
    total: int
    items: list[AgingInvoiceItem] = Field(default_factory=list)


class AgingBucketDetailResponse(BaseModel):
    bucket: str
    limit: int
    offset: int
    tenants: list[TenantAgingDetail] = Field(default_factory=list)


# ── Top Customers Detail ───────────────────────────────────────────────────────

class CustomerContact(BaseModel):
    email: str = ""
    phone: str = ""
    city: str = ""
    country: str = ""
    is_customer: bool = True


class CustomerOrderLine(BaseModel):
    id: int
    product_name: str
    product_code: str
    description: str
    quantity: float
    qty_delivered: float
    qty_invoiced: float
    price_unit: float
    discount: float
    price_subtotal: float
    price_total: float
    margin: float


class CustomerOrderReceipt(BaseModel):
    id: int
    odoo_id: int
    order_number: str
    order_date: Optional[str] = None
    order_datetime: Optional[str] = None
    state: str
    invoice_status: str
    currency_code: str
    amount_untaxed: float
    amount_tax: float
    amount_total: float
    margin: float
    company_name: str
    tenant_id: str
    tenant_name: str
    line_count: int
    lines: list[CustomerOrderLine] = Field(default_factory=list)


class CustomerDetail(BaseModel):
    id: int
    name: str
    tenant_id: str
    tenant_name: str
    total_revenue: float
    total_orders: int
    total_margin: float
    contact: CustomerContact
    # Pagination meta for nested orders
    order_total: int
    order_limit: int
    order_offset: int
    orders: list[CustomerOrderReceipt] = Field(default_factory=list)


# ── Product Detail ─────────────────────────────────────────────────────────────

class ProductOrderReceipt(BaseModel):
    order_id: int
    order_number: str
    order_date: Optional[str] = None
    customer_name: str
    quantity_sold: float
    selling_price: float
    discount: float
    total_price: float
    margin: float
    state: str
    invoice_status: str
    company_name: str
    tenant_id: str
    tenant_name: str


class ProductDetail(BaseModel):
    id: int
    name: str
    tenant_id: str
    tenant_name: str
    default_code: str
    product_type: str
    category_name: str
    total_quantity_sold: float
    total_revenue: float
    total_margin: float
    # Pagination meta for nested orders
    order_total: int
    order_limit: int
    order_offset: int
    orders: list[ProductOrderReceipt] = Field(default_factory=list)
