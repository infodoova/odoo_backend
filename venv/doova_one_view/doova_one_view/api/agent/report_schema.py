"""
api/agent/report_schema.py

Official strongly-typed JSON Contract & Pydantic Schemas for `report_data`.
Defines the exact structure for KPI cards, table slots, trend/waterfall charts,
and domain-specific report payloads with full backward compatibility and permissive extra fields.
"""

from typing import Optional, Union, List, Dict, Any
from pydantic import BaseModel, Field, ConfigDict


# ── 1. KPI Card Value Schema ──────────────────────────────────────────────────

class KPICardValue(BaseModel):
    """
    Structured value for a single KPI card on the cover or executive grid.
    Supports raw numeric calculations, pre-formatted strings, and variance indicators.
    """
    model_config = ConfigDict(extra="allow")

    raw: Optional[Union[float, int, str]] = Field(
        default=None,
        description="Raw numeric or string value for calculation/formatting (e.g. 1500000.0)"
    )
    formatted: Optional[str] = Field(
        default=None,
        description="Pre-formatted human-readable display string (e.g. '1,500,000 XAF' or '45.2%')"
    )
    var_text: Optional[str] = Field(
        default=None,
        description="Variance text compared to prior period or benchmark (e.g. '+12.5%' or '-3.2% vs YoY')"
    )
    arrow: Optional[str] = Field(
        default=None,
        description="Visual indicator arrow ('▲', '▼', '►', or '■')"
    )
    var_class: Optional[str] = Field(
        default=None,
        description="CSS styling class ('variance-positive', 'variance-negative', 'variance-neutral')"
    )
    subtitle: Optional[str] = Field(
        default=None,
        description="Optional subtitle or description below the KPI card value"
    )


# ── 2. Tabular Data Row Schemas ───────────────────────────────────────────────

class ProductRow(BaseModel):
    model_config = ConfigDict(extra="allow")
    name: str
    sku: Optional[str] = None
    category: Optional[str] = None
    qty: Optional[Union[int, float, str]] = None
    revenue: Optional[Union[float, str]] = None
    margin: Optional[Union[float, str]] = None
    unit_price: Optional[Union[float, str]] = None


class CustomerRow(BaseModel):
    model_config = ConfigDict(extra="allow")
    name: str
    orders: Optional[Union[int, str]] = None
    revenue: Optional[Union[float, str]] = None
    share: Optional[Union[float, str]] = None
    ar_balance: Optional[Union[float, str]] = None


class SupplierRow(BaseModel):
    model_config = ConfigDict(extra="allow")
    name: str
    po_count: Optional[Union[int, str]] = None
    spend: Optional[Union[float, str]] = None
    share: Optional[Union[float, str]] = None
    ap_balance: Optional[Union[float, str]] = None


class StockAlertRow(BaseModel):
    model_config = ConfigDict(extra="allow")
    name: str
    sku: Optional[str] = None
    qty: Optional[Union[int, float, str]] = None
    min_qty: Optional[Union[int, float, str]] = None
    unit: Optional[str] = "Units"
    urgency: Optional[str] = "High"


class AgingSchedule(BaseModel):
    model_config = ConfigDict(extra="allow")
    current: Optional[Union[float, str]] = "0"
    days_30: Optional[Union[float, str]] = "0"
    days_60: Optional[Union[float, str]] = "0"
    days_90_plus: Optional[Union[float, str]] = "0"
    total_overdue: Optional[Union[float, str]] = "0"


class ScenarioRow(BaseModel):
    model_config = ConfigDict(extra="allow")
    metric: str
    base: Union[float, str]
    bull: Optional[Union[float, str]] = None
    bear: Optional[Union[float, str]] = None
    variance_bull: Optional[str] = None
    variance_bear: Optional[str] = None


class MonthlyDataPoint(BaseModel):
    model_config = ConfigDict(extra="allow")
    period: str
    revenue: Optional[Union[float, str]] = None
    cogs: Optional[Union[float, str]] = None
    gross_profit: Optional[Union[float, str]] = None
    opex: Optional[Union[float, str]] = None
    ebit: Optional[Union[float, str]] = None
    net_profit: Optional[Union[float, str]] = None


# ── 3. Chart Data Schemas ─────────────────────────────────────────────────────

class TrendDataPoint(BaseModel):
    model_config = ConfigDict(extra="allow")
    period: str
    revenue: Optional[float] = 0.0
    expenses: Optional[float] = 0.0
    net_profit: Optional[float] = 0.0
    spend: Optional[float] = 0.0
    orders: Optional[int] = 0


class WaterfallData(BaseModel):
    model_config = ConfigDict(extra="allow")
    revenue: Optional[float] = 0.0
    cogs: Optional[float] = 0.0
    gross_profit: Optional[float] = None
    opex: Optional[float] = 0.0
    ebit: Optional[float] = None
    tax: Optional[float] = 0.0
    net_profit: Optional[float] = None


# ── 4. Main Report Data Contract ──────────────────────────────────────────────

class ReportDataContract(BaseModel):
    """
    Formal JSON contract for `report_data`.
    Accepts all domain-specific KPI slots, tables, chart arrays, and custom fields.
    """
    model_config = ConfigDict(extra="allow")

    # Common Financial / Performance KPIs
    revenue: Optional[Union[KPICardValue, float, int, str]] = None
    gross_profit: Optional[Union[KPICardValue, float, int, str]] = None
    net_profit: Optional[Union[KPICardValue, float, int, str]] = None
    ebit: Optional[Union[KPICardValue, float, int, str]] = None
    sales_volume: Optional[Union[KPICardValue, float, int, str]] = None
    avg_order_value: Optional[Union[KPICardValue, float, int, str]] = None
    gross_margin_pct: Optional[Union[KPICardValue, float, int, str]] = None
    operating_margin_pct: Optional[Union[KPICardValue, float, int, str]] = None
    net_margin_pct: Optional[Union[KPICardValue, float, int, str]] = None

    # Purchasing & Payables KPIs
    total_spend: Optional[Union[KPICardValue, float, int, str]] = None
    po_count: Optional[Union[KPICardValue, float, int, str]] = None
    active_vendors: Optional[Union[KPICardValue, float, int, str]] = None
    avg_po_value: Optional[Union[KPICardValue, float, int, str]] = None
    ap_balance: Optional[Union[KPICardValue, float, int, str]] = None

    # Treasury & Cash Flow KPIs
    cash_balance: Optional[Union[KPICardValue, float, int, str]] = None
    operating_cashflow: Optional[Union[KPICardValue, float, int, str]] = None
    investing_cashflow: Optional[Union[KPICardValue, float, int, str]] = None
    financing_cashflow: Optional[Union[KPICardValue, float, int, str]] = None
    runway_months: Optional[Union[KPICardValue, float, int, str]] = None
    burn_rate: Optional[Union[KPICardValue, float, int, str]] = None

    # Inventory KPIs
    inventory_value: Optional[Union[KPICardValue, float, int, str]] = None
    total_skus: Optional[Union[KPICardValue, float, int, str]] = None
    turnover_ratio: Optional[Union[KPICardValue, float, int, str]] = None
    days_on_hand: Optional[Union[KPICardValue, float, int, str]] = None

    # Balance Sheet KPIs
    total_assets: Optional[Union[KPICardValue, float, int, str]] = None
    current_assets: Optional[Union[KPICardValue, float, int, str]] = None
    total_liabilities: Optional[Union[KPICardValue, float, int, str]] = None
    current_liabilities: Optional[Union[KPICardValue, float, int, str]] = None
    total_equity: Optional[Union[KPICardValue, float, int, str]] = None
    current_ratio: Optional[Union[KPICardValue, float, int, str]] = None
    quick_ratio: Optional[Union[KPICardValue, float, int, str]] = None
    health_score: Optional[Union[KPICardValue, float, int, str]] = None

    # Forecast / Pro Forma KPIs
    projected_revenue: Optional[Union[KPICardValue, float, int, str]] = None
    projected_growth: Optional[Union[KPICardValue, float, int, str]] = None
    projected_net_income: Optional[Union[KPICardValue, float, int, str]] = None
    target_margin: Optional[Union[KPICardValue, float, int, str]] = None

    # Tables & Lists
    top_products: Optional[List[Union[ProductRow, Dict[str, Any]]]] = None
    top_customers: Optional[List[Union[CustomerRow, Dict[str, Any]]]] = None
    top_suppliers: Optional[List[Union[SupplierRow, Dict[str, Any]]]] = None
    low_stock_alerts: Optional[List[Union[StockAlertRow, Dict[str, Any]]]] = None
    proforma_scenarios: Optional[List[Union[ScenarioRow, Dict[str, Any]]]] = None
    monthly_data: Optional[List[Union[MonthlyDataPoint, Dict[str, Any]]]] = None
    ar_aging: Optional[Union[AgingSchedule, Dict[str, Any]]] = None
    ap_aging: Optional[Union[AgingSchedule, Dict[str, Any]]] = None

    # Chart arrays & direct vector strings
    trend_data: Optional[List[Union[TrendDataPoint, Dict[str, Any]]]] = None
    waterfall_data: Optional[Union[WaterfallData, Dict[str, Any]]] = None
    chart_1_b64: Optional[str] = None
    chart_2_b64: Optional[str] = None

    @classmethod
    def from_payload(cls, data: Optional[Dict[str, Any]]) -> "ReportDataContract":
        """
        Safely construct a validated ReportDataContract instance from any raw dictionary.
        """
        if not data or not isinstance(data, dict):
            return cls()
        return cls.model_validate(data)

    def to_template_dict(self) -> Dict[str, Any]:
        """
        Converts contract to clean dict ready for Jinja2 template consumption.
        """
        return self.model_dump(exclude_none=True)
