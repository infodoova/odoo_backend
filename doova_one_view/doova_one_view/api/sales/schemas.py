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
    value: Union[str, int, float, List[Any], None]


class AdvancedSearchRequest(BaseModel):
    """Request schema for advanced search"""
    filters: List[SearchFilter]
    limit: int = Field(50, ge=1, le=500)
    offset: int = Field(0, ge=0)


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
