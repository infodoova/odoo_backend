"""
Inventory API schemas
"""

from pydantic import BaseModel, ConfigDict, Field
from typing import Any, Optional, List, Union
from datetime import datetime
from doova_one_view.api.common.schemas import ProductRead, LotRead, PaginatedResponse


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
