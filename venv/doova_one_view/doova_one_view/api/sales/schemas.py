"""
Sales API schemas
"""

from pydantic import BaseModel, Field, ConfigDict, field_validator
from typing import Optional, List, Union, Any, Dict
from datetime import datetime, date
from doova_one_view.api.common.schemas import (
    PartnerRead, UserRead, CompanyRead, ProductRead, PaginatedResponse
)
from datetime import datetime, date





class SalesOrderLineRead(BaseModel):
    """Sales order line schema"""
    id: int
    odoo_id: int
    product: Optional[ProductRead] = None
    product_uom_qty: float
    qty_delivered: float
    qty_invoiced: float
    price_unit: float
    price_subtotal: float
    price_total: float
    discount: float
    margin: float
    purchase_price: float
    
    model_config = ConfigDict(from_attributes=True)


class SalesOrderRead(BaseModel):
    """Sales order schema"""
    id: int
    odoo_id: int
    odoo_name: Optional[str]
    partner: Optional[PartnerRead] = None
    user: Optional[UserRead] = None
    company: Optional[CompanyRead] = None
    date_order: datetime
    state: str
    invoice_status: Optional[str]
    amount_untaxed: float
    amount_tax: float
    amount_total: float
    margin: float
    currency_code: Optional[str]
    synced_at: datetime
    
    model_config = ConfigDict(from_attributes=True)


class SalesOrderWithLinesRead(SalesOrderRead):
    """Sales order with lines"""
    lines: List[SalesOrderLineRead]

    @field_validator('lines', mode='before')
    @classmethod
    def convert_django_manager(cls, v):
        if hasattr(v, 'all'):
            return list(v.all())
        return v


class SalesSummary(BaseModel):
    """Sales summary dashboard schema"""
    total_count: int
    total_amount: float
    total_margin: float
    average_order_value: float
    invoiced_percentage: float


class SearchFilter(BaseModel):
    """Filter criteria for advanced search"""
    field: str
    operator: str  # eq, gt, lt, between, contains, startswith, endswith, after, before
    value: Optional[Union[str, int, float, List[Any], None]] = None
    max_value: Optional[Union[str, int, float, None]] = None
    maxValue: Optional[Union[str, int, float, None]] = None

    model_config = ConfigDict(extra='allow')


class AdvancedSearchRequest(BaseModel):
    """Request schema for advanced search"""
    filters: List[SearchFilter]
    limit: int = Field(50, ge=1, le=500)
    offset: int = Field(0, ge=0)

    model_config = ConfigDict(extra='allow')


class KPIMetric(BaseModel):
    """Single KPI metric with optional comparison"""
    value: float
    previous_value: Optional[float] = None
    change_percentage: Optional[float] = None


class TimeSeriesPoint(BaseModel):
    """Data point for time-series charts"""
    date: date
    value: float


class EntityMetric(BaseModel):
    """Metric for a specific entity (Customer, Product, etc)"""
    id: Optional[int] = None
    name: str
    value: float


class SalesDashboard(BaseModel):
    """Comprehensive sales dashboard schema"""
    # Key Summary Metrics
    total_revenue: KPIMetric
    total_profit: KPIMetric
    profit_margin_pct: KPIMetric
    avg_order_value: KPIMetric
    pipeline_value: KPIMetric  # Draft/Sent orders
    
    # Operational Metrics
    order_count: int
    conversion_rate: float # Draft -> Sale
    
    # Trends & Distributions
    revenue_trend: List[TimeSeriesPoint]
    state_distribution: Dict[str, int]
    
    # Rankings
    top_customers: List[EntityMetric]
    top_products: List[EntityMetric]
    top_salespeople: List[EntityMetric]


# ── New PostgreSQL-aligned Schemas ──────────────────────────────────────────

class CountMetric(BaseModel):
    """Same shape as KPIMetric but kept as a separate class for clarity in routes."""
    value: float
    previous_value: float
    change_pct: float

# ── Entity refs ────────────────────────────────────────────────────────────

class Partner(BaseModel):
    id: int
    name: str

class User(BaseModel):
    id: int
    name: str

class Company(BaseModel):
    id: int
    name: str

class Product(BaseModel):
    id: int
    name: str
    sku: str

# ── Order shapes ───────────────────────────────────────────────────────────

class OrderListItem(BaseModel):
    id: int
    name: str
    date_order: str
    state: str
    invoice_status: Optional[str]
    amount_total: float
    currency: str
    partner: Optional[Partner]
    user: Optional[User]
    company: Optional[Company]

class OrderLine(BaseModel):
    id: int
    product: Optional[Product]
    quantity: float
    price_unit: float
    subtotal: float

class OrderDetail(OrderListItem):
    """Full order — adds line items to the list-item shape."""
    lines: list[OrderLine] = Field(default_factory=list)

class OrderListResponse(BaseModel):
    items: list[OrderListItem] = Field(default_factory=list)
    total: int
    limit: int
    offset: int
    applied_filters: dict[str, Any] = Field(default_factory=dict)

# ── Dashboard ──────────────────────────────────────────────────────────────

class DashboardResponse(BaseModel):
    total_revenue: KPIMetric
    order_count: CountMetric
    avg_order_value: KPIMetric
    gross_margin: KPIMetric
    top_customers: list[EntityMetric] = Field(default_factory=list)
    top_products: list[EntityMetric] = Field(default_factory=list)
    revenue_trend: list[TimeSeriesPoint] = Field(default_factory=list)
    state_distribution: dict[str, int] = Field(default_factory=dict)
    applied_filters: dict[str, Any] = Field(default_factory=dict)

# ── Filters meta ───────────────────────────────────────────────────────────

class FiltersResponse(BaseModel):
    state: list[str] = Field(default_factory=list)
    invoice_status: list[str] = Field(default_factory=list)
    currencies: list[str] = Field(default_factory=list)

# ── Search ─────────────────────────────────────────────────────────────────

class SearchRequest(BaseModel):
    filters: list[SearchFilter] = Field(default_factory=list)
    limit: int = 50
    offset: int = 0
    companies: Optional[str] = None
    company_id: Optional[Union[int, str, list[int]]] = None

    model_config = ConfigDict(extra='allow')

class MetricDetailOrder(BaseModel):
    id: int
    odoo_id: int
    odoo_name: Optional[str]
    company_id: Optional[int] = None
    company_name: Optional[str] = None
    customer: Optional[PartnerRead] = None
    salesperson: Optional[UserRead] = None
    date_order: datetime
    state: str
    amount_total: float
    margin: float
    currency_code: Optional[str]
    lines: List[SalesOrderLineRead]
    converted_amount: float
    converted_margin: float
    
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
    
    items: List[MetricDetailOrder]
    total: int
    limit: int
    offset: int


class DailyOrdersResponse(BaseModel):
    """Response for orders on a specific day (Daily Performance drill-down)"""
    date: str                        # YYYY-MM-DD of the requested day
    base_currency: str
    total_revenue: float             # sum of converted amount_total
    order_count: int                 # total orders on this day
    company_groups: List[MetricDetailCompanyGroup]
    items: List[MetricDetailOrder]
    total: int
    limit: int
    offset: int


class MarketBreakdownResponse(BaseModel):
    """Drill-down into a Market-breakdown entity (customer, product, salesperson)"""
    section: str                     # top_customers | top_products | top_salespeople
    entity_id: int                   # partner_id / product_id / user_id
    entity_name: str
    base_currency: str
    total_revenue: float
    order_count: int
    company_groups: List[MetricDetailCompanyGroup]
    items: List[MetricDetailOrder]
    total: int
    limit: int
    offset: int


class EntityProfileResponse(BaseModel):
    """Profile details for a salesperson (User) or customer/key account (Partner)"""
    entity_type: str                   # "salesperson" or "customer"
    id: int                            # Django pk
    odoo_id: int
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    # Partner-only fields
    city: Optional[str] = None
    country_code: Optional[str] = None
    is_customer: Optional[bool] = None
    is_supplier: Optional[bool] = None
    customer_rank: Optional[int] = None
    supplier_rank: Optional[int] = None
    is_active: Optional[bool] = None
    created_at: Optional[datetime] = None    # date started / date synced


class ProductSaleLineDetail(BaseModel):
    """A single sale-line occurrence of a product"""
    line_id: int
    order_id: int
    order_odoo_id: int
    order_name: Optional[str] = None
    date_order: datetime
    company_id: Optional[int] = None
    company_name: Optional[str] = None
    customer_name: Optional[str] = None
    product_uom_qty: float             # pieces ordered
    qty_delivered: float
    qty_invoiced: float
    price_unit: float
    discount: float
    price_subtotal: float
    price_total: float
    margin: float
    currency_code: Optional[str] = None
    converted_subtotal: float
    converted_total: float


class ProductSalesDetailResponse(BaseModel):
    """Drill-down for a product — every sale line with order context"""
    product_id: int
    product_name: str
    product_sku: Optional[str] = None
    product_type: Optional[str] = None
    list_price: Optional[float] = None
    base_currency: str
    total_revenue: float
    total_qty_sold: float
    line_count: int
    company_groups: List[MetricDetailCompanyGroup]
    items: List[ProductSaleLineDetail]
    total: int
    limit: int
    offset: int

class CustomerMetric(BaseModel):
    partner_id: int
    partner_name: str
    order_count: int
    first_order_date: datetime
    last_order_date: datetime
    lifespan_days: int
    lifespan_months: float
    frequency_per_year: float
    frequency_per_month: float

class CustomerMetricsResponse(BaseModel):
    tenant_id: str
    average_lifespan_days: float
    average_lifespan_months: float
    average_frequency_per_year: float
    average_frequency_per_month: float
    total_customers: int
    items: List[CustomerMetric]

CompanyRef = Company
PartnerRef = Partner
UserRef = User
ProductRef = Product
