"""
Master Data API schemas (Products, Partners)
"""

from pydantic import BaseModel, ConfigDict
from typing import Optional, List
from datetime import datetime
from doova_one_view.api.common.schemas import PaginatedResponse


class ProductRead(BaseModel):
    """Product schema"""
    id: int
    odoo_id: int
    name: str
    default_code: Optional[str]
    barcode: Optional[str]
    product_type: Optional[str]
    category_id: Optional[int]
    list_price: Optional[float]
    standard_price: Optional[float]
    uom_name: Optional[str]
    is_active: bool
    
    model_config = ConfigDict(from_attributes=True)


class PartnerRead(BaseModel):
    """Partner schema"""
    id: int
    odoo_id: int
    name: str
    partner_type: Optional[str]
    is_customer: bool
    is_supplier: bool
    email: Optional[str]
    phone: Optional[str]
    city: Optional[str]
    is_active: bool
    
    model_config = ConfigDict(from_attributes=True)


class CurrencyRead(BaseModel):
    """Currency schema"""
    id: int
    odoo_id: int
    code: str
    symbol: Optional[str]
    is_active: bool
    symbol_position: Optional[str]
    rounding: Optional[float]
    
    model_config = ConfigDict(from_attributes=True)
