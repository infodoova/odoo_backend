"""
Inventory API schemas
"""

from pydantic import BaseModel, ConfigDict, Field
from typing import Any, Optional, List, Union
from datetime import datetime
from doova_one_view.api.common.schemas import ProductRead, LotRead, PaginatedResponse, PartnerRead, CompanyRead


class StockQuantRead(BaseModel):
    """Stock quant (current level) schema"""
    id: int
    odoo_id: int
    product: Optional[ProductRead] = None
    lot: Optional[LotRead] = None
    location_name: Optional[str]
    quantity: float
    reserved_quantity: float
    available_quantity: float
    in_date: Optional[datetime]
    synced_at: datetime
    
    model_config = ConfigDict(from_attributes=True)


class StockMoveRead(BaseModel):
    """Stock move schema"""
    id: int
    odoo_id: int
    picking_id: Optional[int]
    product: Optional[ProductRead] = None
    location_src: Optional[str]
    location_dest: Optional[str]
    product_uom_qty: float
    quantity_done: float
    date: datetime
    state: str
    reference: Optional[str]
    
    model_config = ConfigDict(from_attributes=True)


class InventorySummary(BaseModel):
    """Inventory summary dashboard schema"""
    total_products_in_stock: int
    total_quantity: float
    total_reserved_quantity: float
    recent_moves_count: int


class StockTopCardItem(BaseModel):
    """A single product entry inside a top-card drill-down."""
    product_id: Optional[int] = None
    product_name: Optional[str] = None
    product_sku: Optional[str] = None
    location_name: Optional[str] = None
    quantity: float = 0
    reserved_quantity: float = 0
    available_quantity: float = 0


class StockTopCard(BaseModel):
    """One top-level KPI card."""
    key: str
    label: str
    value: float
    unit: str = "qty"
    items: List[StockTopCardItem] = Field(default_factory=list)
    item_count: int = 0


class StockTopCardsResponse(BaseModel):
    """Response for the /dashboard/top-cards endpoint."""
    cards: List[StockTopCard]
    applied_filters: Optional[dict] = None


class SearchFilter(BaseModel):
    """Filter criteria for advanced inventory search."""
    field: str
    operator: str
    value: Union[str, int, float, List[Any], None] = None
    maxValue: Union[str, int, float, None] = None
    max_value: Union[str, int, float, None] = None


class SearchRequest(BaseModel):
    """Advanced inventory search request."""
    filters: List[SearchFilter] = Field(default_factory=list)
    limit: int = Field(50, ge=1, le=500)
    offset: int = Field(0, ge=0)
    company_id: Optional[int] = None
    companies: Optional[Union[str, int, List[Union[str, int]]]] = None


class StockPickingRead(BaseModel):
    """Stock picking schema"""
    id: int
    odoo_id: int
    name: str
    partner: Optional[PartnerRead] = None
    partner_id: Optional[int] = None
    partner_name: Optional[str] = None
    picking_type: str
    picking_type_code: str
    origin: Optional[str] = None
    state: str
    scheduled_date: Optional[datetime] = None
    date_done: Optional[datetime] = None
    company: Optional[CompanyRead] = None
    company_id: Optional[int] = None
    company_name: Optional[str] = None
    synced_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MetricDetailCompanyGroup(BaseModel):
    company_id: Optional[int] = None
    company_name: str
    metric_value: float


class MetricDetailResponse(BaseModel):
    metric_name: str
    total_metric_value: float
    company_groups: List[MetricDetailCompanyGroup]
    items: List[Union[StockQuantRead, StockPickingRead]]
    total: int
    limit: int
    offset: int


class DailyMovesResponse(BaseModel):
    date: str
    total_quantity: float
    picking_count: int
    company_groups: List[MetricDetailCompanyGroup]
    items: List[Union[StockQuantRead, StockPickingRead]]
    total: int
    limit: int
    offset: int


class MarketBreakdownResponse(BaseModel):
    section: str
    entity_id: Union[int, str]
    entity_name: str
    total_quantity: float
    company_groups: List[MetricDetailCompanyGroup]
    items: List[StockQuantRead]
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


class ProductInventoryDetailResponse(BaseModel):
    product_id: int
    product_name: str
    product_sku: Optional[str] = None
    product_type: Optional[str] = None
    list_price: Optional[float] = None
    total_quantity: float
    total_reserved: float
    line_count: int
    company_groups: List[MetricDetailCompanyGroup]
    items: List[StockQuantRead]
    total: int
    limit: int
    offset: int


class AlertItem(BaseModel):
    id: int
    title: str
    description: Optional[str] = None
    date: Optional[str] = None

class AlertGroup(BaseModel):
    key: str
    label: str
    count: int
    severity: str
    items: List[AlertItem] = Field(default_factory=list)

class InventoryAlertsResponse(BaseModel):
    alerts: List[AlertGroup]
