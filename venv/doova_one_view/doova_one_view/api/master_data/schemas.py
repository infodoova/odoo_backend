"""
Master Data API schemas (Products, Partners)
"""

from pydantic import BaseModel, ConfigDict, Field
from typing import Any, Optional, List, Union
from datetime import datetime
from uuid import UUID
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


class CompanyRead(BaseModel):
    """Company schema"""
    id: int
    tenant_id: Optional[UUID | str]
    odoo_id: int
    name: str
    currency_code: Optional[str] = ""
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


class SearchFilter(BaseModel):
    """Filter criteria for master-data search."""
    field: str
    operator: str
    value: Union[str, int, float, bool, List[Any], None] = None
    maxValue: Union[str, int, float, None] = None
    max_value: Union[str, int, float, None] = None


class SearchRequest(BaseModel):
    """Advanced master-data search request."""
    filters: List[SearchFilter] = Field(default_factory=list)
    limit: int = Field(50, ge=1, le=500)
    offset: int = Field(0, ge=0)
    company_id: Optional[int] = None
    companies: Optional[Union[str, int, List[Union[str, int]]]] = None
