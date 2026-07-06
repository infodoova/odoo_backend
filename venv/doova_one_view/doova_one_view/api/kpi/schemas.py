from typing import Any, Optional

from pydantic import BaseModel, Field


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
