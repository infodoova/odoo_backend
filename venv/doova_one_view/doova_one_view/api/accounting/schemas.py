"""
Accounting API schemas
"""

from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing import Any, Optional, List, Union
from datetime import datetime, date
from doova_one_view.api.common.schemas import (
    PartnerRead, CompanyRead, ProductRead, PaginatedResponse
)


class AccountMoveLineRead(BaseModel):
    """Account move line schema"""
    id: int
    odoo_id: int
    product: Optional[ProductRead] = None
    account_code: Optional[str]
    account_name: Optional[str]
    debit: float
    credit: float
    balance: float
    quantity: float
    price_unit: float
    price_subtotal: float
    name: Optional[str]
    
    model_config = ConfigDict(from_attributes=True)


class AccountMoveRead(BaseModel):
    """Account move schema"""
    id: int
    odoo_id: int
    odoo_name: Optional[str]
    partner: Optional[PartnerRead] = None
    company: Optional[CompanyRead] = None
    date: date
    invoice_date: Optional[date]
    invoice_date_due: Optional[date]
    move_type: str
    state: str
    payment_state: Optional[str]
    amount_untaxed: float
    amount_tax: float
    amount_total: float
    amount_residual: float
    currency_code: Optional[str]
    ref: Optional[str]
    synced_at: datetime
    
    model_config = ConfigDict(from_attributes=True)


class AccountMoveWithLinesRead(AccountMoveRead):
    """Account move with lines"""
    lines: List[AccountMoveLineRead]

    @field_validator('lines', mode='before')
    @classmethod
    def convert_django_manager(cls, v):
        if hasattr(v, 'all'):
            return list(v.all())
        return v


class AccountingSummary(BaseModel):
    """Accounting summary dashboard schema"""
    total_invoiced: float
    total_bills: float
    total_receivable: float
    total_payable: float
    net_profit_estimate: float


class SearchFilter(BaseModel):
    """Filter criteria for advanced accounting search."""
    field: str
    operator: str
    value: Union[str, int, float, List[Any], None] = None
    maxValue: Union[str, int, float, None] = None
    max_value: Union[str, int, float, None] = None


class SearchRequest(BaseModel):
    """Advanced search request."""
    filters: List[SearchFilter] = Field(default_factory=list)
    limit: int = Field(50, ge=1, le=500)
    offset: int = Field(0, ge=0)
    company_id: Optional[int] = None
    companies: Optional[Union[str, int, List[Union[str, int]]]] = None
