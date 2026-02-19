"""
Purchase API schemas
"""

from pydantic import BaseModel, ConfigDict, field_validator
from typing import Optional, List
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
