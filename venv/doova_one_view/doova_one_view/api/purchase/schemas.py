"""
Purchase API schemas
"""

from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing import Any, Optional, List, Union
from datetime import datetime
from doova_one_view.api.common.schemas import (
    PartnerRead, UserRead, CompanyRead, ProductRead, PaginatedResponse
)


class PurchaseOrderLineRead(BaseModel):
    """Purchase order line schema"""
    id: int
    odoo_id: int
    product: Optional[ProductRead] = None
    product_qty: float
    qty_received: float
    qty_invoiced: float
    price_unit: float
    price_subtotal: float
    price_total: float
    name: Optional[str]
    
    model_config = ConfigDict(from_attributes=True)


class PurchaseOrderRead(BaseModel):
    """Purchase order schema"""
    id: int
    odoo_id: int
    odoo_name: Optional[str]
    partner: Optional[PartnerRead] = None
    user: Optional[UserRead] = None
    company: Optional[CompanyRead] = None
    date_order: datetime
    date_planned: Optional[datetime]
    state: str
    invoice_status: Optional[str]
    amount_untaxed: float
    amount_tax: float
    amount_total: float
    currency_code: Optional[str]
    synced_at: datetime
    
    model_config = ConfigDict(from_attributes=True)


class PurchaseOrderWithLinesRead(PurchaseOrderRead):
    """Purchase order with lines"""
    lines: List[PurchaseOrderLineRead]

    @field_validator('lines', mode='before')
    @classmethod
    def convert_django_manager(cls, v):
        if hasattr(v, 'all'):
            return list(v.all())
        return v


class PurchaseSummary(BaseModel):
    """Purchase summary dashboard schema"""
    total_count: int
    total_amount: float
    average_order_value: float
    billed_percentage: float


class SearchFilter(BaseModel):
    """Filter criteria for advanced purchase search."""
    field: str
    operator: str
    value: Union[str, int, float, List[Any], None] = None
    max_value: Optional[Union[str, int, float, None]] = None


class SearchRequest(BaseModel):
    """Advanced search request."""
    filters: List[SearchFilter] = Field(default_factory=list)
    limit: int = Field(50, ge=1, le=500)
    offset: int = Field(0, ge=0)
    companies: Optional[str] = None


# ── Drill-Down Schemas ──────────────────────────────────────────────────────────

class PurchaseMetricDetailOrder(BaseModel):
    id: int
    odoo_id: int
    odoo_name: Optional[str]
    company_id: Optional[int] = None
    company_name: Optional[str] = None
    vendor: Optional[PartnerRead] = None
    buyer: Optional[UserRead] = None
    date_order: datetime
    state: str
    amount_total: float
    currency_code: Optional[str]
    lines: List[PurchaseOrderLineRead]
    converted_amount: float
    
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
    items: List[PurchaseMetricDetailOrder]
    total: int
    limit: int
    offset: int


class DailyOrdersResponse(BaseModel):
    date: str
    base_currency: str
    total_spend: float
    order_count: int
    company_groups: List[MetricDetailCompanyGroup]
    items: List[PurchaseMetricDetailOrder]
    total: int
    limit: int
    offset: int


class MarketBreakdownResponse(BaseModel):
    section: str
    entity_id: int
    entity_name: str
    base_currency: str
    total_spend: float
    order_count: int
    company_groups: List[MetricDetailCompanyGroup]
    items: List[PurchaseMetricDetailOrder]
    total: int
    limit: int
    offset: int


class ProductPurchaseDetailResponse(BaseModel):
    product_id: int
    product_name: str
    product_sku: Optional[str] = None
    product_type: Optional[str] = None
    list_price: Optional[float] = None
    base_currency: str
    total_spend: float
    total_qty_purchased: float
    line_count: int
    company_groups: List[MetricDetailCompanyGroup]
    items: List[PurchaseOrderLineRead]
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
