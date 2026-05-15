
from pydantic import BaseModel, ConfigDict
from typing import Optional, List, TypeVar, Generic
from datetime import date

T = TypeVar('T')

class PaginatedResponse(BaseModel, Generic[T]):
    """Generic paginated response schema"""
    items: List[T]
    total: int
    limit: int
    offset: int

class PartnerRead(BaseModel):
    """Partner schema"""
    id: int
    odoo_id: int
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    country_code: Optional[str] = None
    city: Optional[str] = None
    is_customer: bool
    is_supplier: bool
    
    model_config = ConfigDict(from_attributes=True)


class UserRead(BaseModel):
    """User schema"""
    id: int
    odoo_id: int
    name: str
    email: Optional[str] = None
    
    model_config = ConfigDict(from_attributes=True)


class CompanyRead(BaseModel):
    """Company schema"""
    id: int
    odoo_id: int
    name: str
    currency_code: Optional[str] = None
    country_code: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class ProductRead(BaseModel):
    """Product schema"""
    id: int
    odoo_id: int
    name: str
    default_code: Optional[str] = None
    barcode: Optional[str] = None
    product_type: Optional[str] = None
    list_price: Optional[float] = None
    standard_price: Optional[float] = None
    uom_name: Optional[str] = None
    
    model_config = ConfigDict(from_attributes=True)


class LotRead(BaseModel):
    """Lot/Serial number schema"""
    id: int
    odoo_id: int
    name: str
    ref: Optional[str] = None
    expiration_date: Optional[date] = None
    
    model_config = ConfigDict(from_attributes=True)
