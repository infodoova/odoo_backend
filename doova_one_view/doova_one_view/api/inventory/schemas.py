"""
Inventory API schemas
"""

from pydantic import BaseModel, ConfigDict
from typing import Optional, List
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
