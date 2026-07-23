"""
Account Journals API schemas.
"""

from pydantic import BaseModel, ConfigDict, Field, AliasChoices
from typing import Any, Optional, List, Union
from datetime import datetime
from doova_one_view.api.common.schemas import CompanyRead


class AccountJournalRead(BaseModel):
    """Account journal schema"""
    id: int
    odoo_id: int
    name: str
    code: Optional[str] = None
    type: Optional[str] = None
    currency_code: Optional[str] = None
    company: Optional[CompanyRead] = None
    default_account_id: Optional[int] = None
    default_account_code: Optional[str] = None
    synced_at: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)


class SearchFilter(BaseModel):
    """Filter criteria for account journals search."""
    field: str = Field(validation_alias=AliasChoices("field", "column"))
    operator: str
    value: Union[str, int, float, bool, List[Any], None] = None
    maxValue: Union[str, int, float, None] = None
    max_value: Union[str, int, float, None] = None


class SearchRequest(BaseModel):
    """Advanced account journals search request."""
    filters: List[SearchFilter] = Field(default_factory=list)
    limit: int = Field(50, ge=1, le=500)
    offset: int = Field(0, ge=0)
    company_id: Optional[int] = None
    companies: Optional[Union[str, int, List[Union[str, int]]]] = None
