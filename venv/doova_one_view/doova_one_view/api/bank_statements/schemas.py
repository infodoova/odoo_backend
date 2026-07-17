"""
Bank Statements API schemas.
"""

from pydantic import BaseModel, ConfigDict, Field, AliasChoices
from typing import Any, Optional, List, Union
from datetime import date, datetime
from doova_one_view.api.common.schemas import CompanyRead, PartnerRead


class BankStatementRead(BaseModel):
    """Bank statement schema"""
    id: int
    odoo_id: int
    odoo_name: Optional[str]
    company: Optional[CompanyRead] = None
    date: Optional[date]
    journal_name: Optional[str]
    balance_start: float
    balance_end_real: float
    state: Optional[str]
    synced_at: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)


class BankStatementLineRead(BaseModel):
    """Bank statement line schema"""
    id: int
    odoo_id: int
    statement_id: int
    statement_name: Optional[str] = None
    company: Optional[CompanyRead] = None
    date: Optional[date]
    name: Optional[str]
    amount: float
    partner: Optional[PartnerRead] = None
    ref: Optional[str]
    synced_at: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)


class SearchFilter(BaseModel):
    """Filter criteria for bank statements search."""
    field: str = Field(validation_alias=AliasChoices("field", "column"))
    operator: str
    value: Union[str, int, float, bool, List[Any], None] = None
    maxValue: Union[str, int, float, None] = None
    max_value: Union[str, int, float, None] = None


class SearchRequest(BaseModel):
    """Advanced bank statements search request."""
    filters: List[SearchFilter] = Field(default_factory=list)
    limit: int = Field(50, ge=1, le=500)
    offset: int = Field(0, ge=0)
    company_id: Optional[int] = None
    companies: Optional[Union[str, int, List[Union[str, int]]]] = None
