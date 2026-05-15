from typing import Any

from pydantic import BaseModel, Field


class KPIMetric(BaseModel):
    value: float
    previous_value: float
    change_pct: float
    change_percentage: float


class TimeSeriesPoint(BaseModel):
    date: str
    value: float


class ProductPerformance(BaseModel):
    id: int
    name: str
    revenue: float
    quantity: float
    margin_pct: float


class CustomerPerformance(BaseModel):
    id: int
    name: str
    revenue: float
    orders: int


class OverviewResponse(BaseModel):
    kpis: dict[str, Any]
    tenant_benchmarks: list[dict[str, Any]] = Field(default_factory=list)
    applied_filters: dict[str, Any] = Field(default_factory=dict)
