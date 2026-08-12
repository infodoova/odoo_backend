"""
Account Partial Reconciles API schemas.
"""

from pydantic import BaseModel, ConfigDict, Field, AliasChoices
from typing import Any, Optional, List, Union
from datetime import date, datetime


from doova_one_view.api.accounting.schemas import AccountMoveLineRead

class AccountPartialReconcileRead(BaseModel):
    """Account partial reconcile schema"""
    id: int
    odoo_id: int
    debit_move_line: Optional[AccountMoveLineRead] = None
    credit_move_line: Optional[AccountMoveLineRead] = None
    amount: float
    company_id: Optional[int] = None
    max_date: Optional[date] = None
    synced_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class SearchFilter(BaseModel):
    """Filter criteria for account partial reconciles search."""
    field: str = Field(validation_alias=AliasChoices("field", "column"))
    operator: str
    value: Union[str, int, float, bool, List[Any], None] = None
    maxValue: Union[str, int, float, None] = None
    max_value: Union[str, int, float, None] = None


class SearchRequest(BaseModel):
    """Advanced account partial reconciles search request."""
    filters: List[SearchFilter] = Field(default_factory=list)
    limit: int = Field(50, ge=1, le=500)
    offset: int = Field(0, ge=0)
