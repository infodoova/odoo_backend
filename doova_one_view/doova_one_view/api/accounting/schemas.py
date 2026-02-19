"""
Accounting API schemas
"""

from pydantic import BaseModel, ConfigDict, field_validator
from typing import Optional, List
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
