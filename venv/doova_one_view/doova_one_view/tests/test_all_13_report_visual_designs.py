"""
doova_one_view/tests/test_all_13_report_visual_designs.py

Generates complete, rich, production-grade PDF reports for all 12 domain templates
plus the legacy health template with realistic financial & operational mock data.
Verifies that all 13 reports compile cleanly into valid PDF files with positive byte sizes.
"""

import uuid
import os
from pathlib import Path
from django.test import TestCase

from odoo_app.models.tenant import Tenant
from doova_one_view.api.agent.tools_refactored.reporting_v2 import generate_report_tool, _get_reports_dir


class AllReportTypesVisualDesignTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(id=uuid.uuid4(), name="Acme Enterprises SA")
        self.tenant_id = str(self.tenant.id)
        self.reports_dir = _get_reports_dir()

    def test_generate_all_13_report_types_with_sample_data(self):
        """
        Generate all 12 domain templates + 1 legacy health report with rich realistic data.
        """
        reports_generated = {}

        # ── 1. Sales Report ───────────────────────────────────────────────────
        sales_data = {
            "revenue": {"raw": 12500000, "formatted": "12,500,000 XAF", "var_text": "+18.2%", "arrow": "▲", "var_class": "variance-positive"},
            "sales_volume": {"raw": 3450, "formatted": "3,450 Orders", "var_text": "+12.0%", "arrow": "▲", "var_class": "variance-positive"},
            "avg_order_value": {"raw": 3623, "formatted": "3,623 XAF", "var_text": "+5.5%", "arrow": "▲", "var_class": "variance-positive"},
            "gross_margin_pct": {"raw": 42.5, "formatted": "42.5%", "var_text": "+1.8%", "arrow": "▲", "var_class": "variance-positive"},
            "top_products": [
                {"name": "Solar Hybrid Inverter 5kVA", "qty": 140, "revenue": "4,200,000 XAF", "margin": "44%"},
                {"name": "Lithium Storage Battery 48V", "qty": 85, "revenue": "3,400,000 XAF", "margin": "38%"},
                {"name": "Monocrystalline Solar Panel 450W", "qty": 420, "revenue": "2,100,000 XAF", "margin": "40%"},
                {"name": "Smart Energy Gateway Controller", "qty": 95, "revenue": "1,425,000 XAF", "margin": "52%"},
                {"name": "Installation Kit & Surge Protectors", "qty": 210, "revenue": "1,375,000 XAF", "margin": "48%"},
            ],
            "top_customers": [
                {"name": "Société Camerounaise d'Énergie", "orders": 24, "revenue": "3,800,000 XAF", "share": "30.4%"},
                {"name": "Douala Logistics Hub SA", "orders": 18, "revenue": "2,450,000 XAF", "share": "19.6%"},
                {"name": "Hôtel Mont Fébé Yaoundé", "orders": 12, "revenue": "1,900,000 XAF", "share": "15.2%"},
                {"name": "Agro-Industries du Littoral", "orders": 15, "revenue": "1,650,000 XAF", "share": "13.2%"},
            ],
            "trend_data": [
                {"period": "Jan", "revenue": 1800000, "expenses": 1200000, "net_profit": 600000},
                {"period": "Feb", "revenue": 1950000, "expenses": 1250000, "net_profit": 700000},
                {"period": "Mar", "revenue": 2100000, "expenses": 1300000, "net_profit": 800000},
                {"period": "Apr", "revenue": 2150000, "expenses": 1350000, "net_profit": 800000},
                {"period": "May", "revenue": 2200000, "expenses": 1400000, "net_profit": 800000},
                {"period": "Jun", "revenue": 2300000, "expenses": 1450000, "net_profit": 850000},
            ],
        }
        res = generate_report_tool(
            tenant_id=self.tenant_id,
            report_type="sales",
            report_data=sales_data,
            custom_content="""## Executive Sales Commentary
Sales revenue expanded **+18.2%** during the period, driven by commercial expansion in solar storage systems.

### Strategic Observations
* **Product Mix Acceleration**: The 5kVA Hybrid Inverter accounted for **33.6%** of total turnover with expanding unit margins.
* **Customer Concentration**: Top 4 enterprise clients represent **78.4%** of quarterly volume; cross-selling accessories has expanded average order value to **3,623 XAF**.
* **Action Priority**: Establish automated volume discount tiers for tier-1 distributors in Q3.""",
        )
        self.assertEqual(res["status"], "success")
        reports_generated["sales"] = res

        # ── 2. Purchase Report ────────────────────────────────────────────────
        purchase_data = {
            "total_spend": {"raw": 7800000, "formatted": "7,800,000 XAF", "var_text": "-4.5%", "arrow": "▼", "var_class": "variance-positive"},
            "po_count": {"raw": 142, "formatted": "142 POs", "var_text": "-8.0%", "arrow": "▼", "var_class": "variance-positive"},
            "active_vendors": {"raw": 28, "formatted": "28 Suppliers"},
            "avg_po_value": {"raw": 54930, "formatted": "54,930 XAF", "var_text": "+3.8%", "arrow": "▲", "var_class": "variance-neutral"},
            "top_suppliers": [
                {"name": "Shenzhen Green Energy Corp", "po_count": 18, "spend": "3,120,000 XAF", "share": "40.0%"},
                {"name": "Rotterdam Power Components BV", "po_count": 22, "spend": "1,950,000 XAF", "share": "25.0%"},
                {"name": "Douala Cable & Wiring SARL", "po_count": 34, "spend": "1,400,000 XAF", "share": "17.9%"},
                {"name": "Afrik Logistic Packaging", "po_count": 45, "spend": "780,000 XAF", "share": "10.0%"},
            ],
            "ap_aging": {
                "current": "4,200,000 XAF",
                "days_30": "1,800,000 XAF",
                "days_60": "900,000 XAF",
                "days_90_plus": "400,000 XAF",
                "total_overdue": "1,300,000 XAF",
            },
            "trend_data": [
                {"period": "Jan", "revenue": 1400000, "expenses": 1300000, "net_profit": 100000},
                {"period": "Feb", "revenue": 1350000, "expenses": 1250000, "net_profit": 100000},
                {"period": "Mar", "revenue": 1300000, "expenses": 1200000, "net_profit": 100000},
            ],
        }
        res = generate_report_tool(
            tenant_id=self.tenant_id,
            report_type="purchase",
            report_data=purchase_data,
            custom_content="""## Procurement Spend Analysis
Total procurement spend contracted **-4.5%** as volume consolidation discounts took effect.

### Key Procurement Levers
* **Vendor Consolidation**: Sourcing 65% of active inventory lines through our two primary international suppliers reduced freight surcharges by 14%.
* **Payable Aging**: Overdue payables past 60 days stand at **1.3M XAF**, fully covered by credit lines.""",
        )
        self.assertEqual(res["status"], "success")
        reports_generated["purchase"] = res

        # ── 3. Cash Flow Report ───────────────────────────────────────────────
        cashflow_data = {
            "cash_balance": {"raw": 5400000, "formatted": "5,400,000 XAF", "var_text": "+22.4%", "arrow": "▲", "var_class": "variance-positive"},
            "operating_cashflow": {"raw": 3100000, "formatted": "3,100,000 XAF", "var_text": "+15.0%", "arrow": "▲", "var_class": "variance-positive"},
            "investing_cashflow": {"raw": -850000, "formatted": "(850,000 XAF)"},
            "financing_cashflow": {"raw": -400000, "formatted": "(400,000 XAF)"},
            "runway_months": {"raw": 14.5, "formatted": "14.5 Months"},
            "burn_rate": {"raw": 372000, "formatted": "372,000 XAF/mo"},
            "waterfall_data": {
                "revenue": 12500000,
                "cogs": 7200000,
                "gross_profit": 5300000,
                "opex": 2200000,
                "ebit": 3100000,
                "tax": 620000,
                "net_profit": 2480000,
            },
        }
        res = generate_report_tool(
            tenant_id=self.tenant_id,
            report_type="cashflow",
            report_data=cashflow_data,
            custom_content="""## Treasury & Liquidity Review
Cash reserves increased to **5.4M XAF** supported by positive operating cash flow of **3.1M XAF**.""",
        )
        self.assertEqual(res["status"], "success")
        reports_generated["cashflow"] = res

        # ── 4. Inventory Report ───────────────────────────────────────────────
        inventory_data = {
            "inventory_value": {"raw": 9200000, "formatted": "9,200,000 XAF", "var_text": "+3.2%", "arrow": "▲", "var_class": "variance-neutral"},
            "total_skus": {"raw": 450, "formatted": "450 SKUs"},
            "turnover_ratio": {"raw": 5.2, "formatted": "5.2x / yr", "var_text": "+0.4x", "arrow": "▲", "var_class": "variance-positive"},
            "days_on_hand": {"raw": 70, "formatted": "70 Days", "var_text": "-6 Days", "arrow": "▼", "var_class": "variance-positive"},
            "low_stock_alerts": [
                {"name": "5kVA Inverter Motherboard", "sku": "INV-MB-05", "qty": 3, "min_qty": 15, "unit": "Units"},
                {"name": "Solar Cable 6mm² Red (100m)", "sku": "CAB-6R-100", "qty": 2, "min_qty": 20, "unit": "Rolls"},
                {"name": "DC Circuit Breaker 63A", "sku": "CB-DC-63A", "qty": 5, "min_qty": 30, "unit": "Units"},
            ],
        }
        res = generate_report_tool(
            tenant_id=self.tenant_id,
            report_type="inventory",
            report_data=inventory_data,
            custom_content="""## Warehouse Valuation & Stock Health
Inventory turnover accelerated to **5.2x**, reducing days inventory outstanding (DIO) to **70 days**.""",
        )
        self.assertEqual(res["status"], "success")
        reports_generated["inventory"] = res

        # ── 5. Income Statement Report ────────────────────────────────────────
        pnl_data = {
            "revenue": {"raw": 15000000, "formatted": "15,000,000 XAF", "var_text": "+16.5%", "arrow": "▲", "var_class": "variance-positive"},
            "cogs": {"raw": 8700000, "formatted": "8,700,000 XAF"},
            "gross_profit": {"raw": 6300000, "formatted": "6,300,000 XAF", "var_text": "+21.2%", "arrow": "▲", "var_class": "variance-positive"},
            "opex": {"raw": 3200000, "formatted": "3,200,000 XAF"},
            "ebit": {"raw": 3100000, "formatted": "3,100,000 XAF", "var_text": "+28.4%", "arrow": "▲", "var_class": "variance-positive"},
            "net_profit": {"raw": 2480000, "formatted": "2,480,000 XAF", "var_text": "+25.1%", "arrow": "▲", "var_class": "variance-positive"},
            "net_margin_pct": {"raw": 16.5, "formatted": "16.5%", "var_text": "+1.2%", "arrow": "▲", "var_class": "variance-positive"},
            "waterfall_data": {
                "revenue": 15000000,
                "cogs": 8700000,
                "gross_profit": 6300000,
                "opex": 3200000,
                "ebit": 3100000,
                "tax": 620000,
                "net_profit": 2480000,
            },
        }
        res = generate_report_tool(
            tenant_id=self.tenant_id,
            report_type="income_statement",
            report_data=pnl_data,
            custom_content="""## Comprehensive Profit & Loss Analysis
Operating margin (EBIT) reached **3.1M XAF** (20.7%), demonstrating robust operational unit economics.""",
        )
        self.assertEqual(res["status"], "success")
        reports_generated["income_statement"] = res

        # ── 6. Balance Sheet Report ───────────────────────────────────────────
        bs_data = {
            "total_assets": {"raw": 28500000, "formatted": "28,500,000 XAF"},
            "current_assets": {"raw": 16200000, "formatted": "16,200,000 XAF"},
            "total_liabilities": {"raw": 11400000, "formatted": "11,400,000 XAF"},
            "current_liabilities": {"raw": 7100000, "formatted": "7,100,000 XAF"},
            "total_equity": {"raw": 17100000, "formatted": "17,100,000 XAF"},
            "current_ratio": {"raw": 2.28, "formatted": "2.28x", "var_text": "Healthy", "var_class": "variance-positive"},
            "quick_ratio": {"raw": 1.45, "formatted": "1.45x", "var_text": "Strong", "var_class": "variance-positive"},
        }
        res = generate_report_tool(
            tenant_id=self.tenant_id,
            report_type="balance_sheet",
            report_data=bs_data,
            custom_content="""## Statement of Financial Position
Total enterprise equity stands at **17.1M XAF** with strong liquidity headroom (Current Ratio: 2.28x).""",
        )
        self.assertEqual(res["status"], "success")
        reports_generated["balance_sheet"] = res

        # ── 7. Financial Analysis Report ───────────────────────────────────────
        fin_data = {
            "health_score": {"raw": 88, "formatted": "88/100", "var_text": "Tier 1: Exceptional", "arrow": "▲", "var_class": "variance-positive"},
            "gross_margin_pct": {"raw": 42.0, "formatted": "42.0%"},
            "operating_margin_pct": {"raw": 20.7, "formatted": "20.7%"},
            "current_ratio": {"raw": 2.28, "formatted": "2.28x"},
            "quick_ratio": {"raw": 1.45, "formatted": "1.45x"},
            "roe": {"raw": 14.5, "formatted": "14.5%"},
            "roa": {"raw": 8.7, "formatted": "8.7%"},
        }
        res = generate_report_tool(
            tenant_id=self.tenant_id,
            report_type="financial_analysis",
            report_data=fin_data,
            custom_content="""## Executive Diagnostic Assessment
Composite Business Health Score attained **88/100**, driven by disciplined working capital and margin stability.""",
        )
        self.assertEqual(res["status"], "success")
        reports_generated["financial_analysis"] = res

        # ── 8. Monthly P&L Report ─────────────────────────────────────────────
        monthly_pnl_data = {
            "avg_monthly_revenue": {"raw": 1250000, "formatted": "1,250,000 XAF"},
            "best_month": {"raw": 1680000, "formatted": "Dec (1,680,000 XAF)"},
            "lowest_month": {"raw": 890000, "formatted": "Feb (890,000 XAF)"},
            "volatility_pct": {"raw": 12.4, "formatted": "12.4%"},
            "monthly_data": [
                {"period": "Jan", "revenue": "1,100,000 XAF", "cogs": "640,000 XAF", "opex": "250,000 XAF", "net_profit": "210,000 XAF"},
                {"period": "Feb", "revenue": "890,000 XAF", "cogs": "520,000 XAF", "opex": "240,000 XAF", "net_profit": "130,000 XAF"},
                {"period": "Mar", "revenue": "1,250,000 XAF", "cogs": "720,000 XAF", "opex": "260,000 XAF", "net_profit": "270,000 XAF"},
                {"period": "Apr", "revenue": "1,320,000 XAF", "cogs": "760,000 XAF", "opex": "270,000 XAF", "net_profit": "290,000 XAF"},
                {"period": "May", "revenue": "1,450,000 XAF", "cogs": "840,000 XAF", "opex": "280,000 XAF", "net_profit": "330,000 XAF"},
                {"period": "Jun", "revenue": "1,680,000 XAF", "cogs": "970,000 XAF", "opex": "300,000 XAF", "net_profit": "410,000 XAF"},
            ],
            "trend_data": [
                {"period": "Jan", "revenue": 1100000, "expenses": 890000, "net_profit": 210000},
                {"period": "Feb", "revenue": 890000, "expenses": 760000, "net_profit": 130000},
                {"period": "Mar", "revenue": 1250000, "expenses": 980000, "net_profit": 270000},
                {"period": "Apr", "revenue": 1320000, "expenses": 1030000, "net_profit": 290000},
                {"period": "May", "revenue": 1450000, "expenses": 1120000, "net_profit": 330000},
                {"period": "Jun", "revenue": 1680000, "expenses": 1270000, "net_profit": 410000},
            ],
        }
        res = generate_report_tool(
            tenant_id=self.tenant_id,
            report_type="monthly_pnl",
            report_data=monthly_pnl_data,
            custom_content="""## Trajectory & Seasonality Review
Monthly revenue expanded steadily through H1, culminating in peak performance in June (**1.68M XAF**).""",
        )
        self.assertEqual(res["status"], "success")
        reports_generated["monthly_pnl"] = res

        # ── 9. Pro Forma Report ───────────────────────────────────────────────
        proforma_data = {
            "projected_revenue": {"raw": 18500000, "formatted": "18,500,000 XAF", "var_text": "+23.3%", "arrow": "▲", "var_class": "variance-positive"},
            "projected_growth": {"raw": 23.3, "formatted": "+23.3%"},
            "projected_net_income": {"raw": 3200000, "formatted": "3,200,000 XAF"},
            "target_margin": {"raw": 17.3, "formatted": "17.3%"},
            "proforma_scenarios": [
                {"metric": "Gross Revenue", "base": "18.5M XAF", "bull": "21.2M XAF", "bear": "15.8M XAF", "variance_bull": "+14.6%", "variance_bear": "-14.6%"},
                {"metric": "Gross Profit", "base": "7.8M XAF", "bull": "9.1M XAF", "bear": "6.5M XAF", "variance_bull": "+16.7%", "variance_bear": "-16.7%"},
                {"metric": "Operating Income (EBIT)", "base": "3.9M XAF", "bull": "4.8M XAF", "bear": "2.9M XAF", "variance_bull": "+23.1%", "variance_bear": "-25.6%"},
                {"metric": "Net Earnings", "base": "3.2M XAF", "bull": "3.9M XAF", "bear": "2.3M XAF", "variance_bull": "+21.9%", "variance_bear": "-28.1%"},
            ],
        }
        res = generate_report_tool(
            tenant_id=self.tenant_id,
            report_type="proforma",
            report_data=proforma_data,
            custom_content="""## Forward Financial Forecast (FY2027 Projections)
Base case forecast projects **18.5M XAF** in gross revenues supported by continued commercial expansion.""",
        )
        self.assertEqual(res["status"], "success")
        reports_generated["proforma"] = res

        # ── 10. Consolidated Report ───────────────────────────────────────────
        consolidated_data = {
            "total_revenue": {"raw": 34200000, "formatted": "34,200,000 XAF"},
            "consolidated_ebit": {"raw": 6800000, "formatted": "6,800,000 XAF"},
            "group_net_profit": {"raw": 5100000, "formatted": "5,100,000 XAF"},
            "total_cash": {"raw": 12400000, "formatted": "12,400,000 XAF"},
            "trend_data": [
                {"period": "Q1", "revenue": 7800000, "expenses": 6200000, "net_profit": 1600000},
                {"period": "Q2", "revenue": 8600000, "expenses": 6800000, "net_profit": 1800000},
                {"period": "Q3", "revenue": 8900000, "expenses": 7100000, "net_profit": 1800000},
                {"period": "Q4", "revenue": 8900000, "expenses": 7300000, "net_profit": 1600000},
            ],
        }
        res = generate_report_tool(
            tenant_id=self.tenant_id,
            report_type="consolidated",
            report_data=consolidated_data,
            custom_content="""## Multi-Entity Consolidated Performance Pack
Group-level consolidated revenues closed at **34.2M XAF** with net margins averaging **14.9%** across all operating subsidiaries.""",
        )
        self.assertEqual(res["status"], "success")
        reports_generated["consolidated"] = res

        # ── 11. Accounting Report ─────────────────────────────────────────────
        accounting_data = {
            "trial_balance_debit": {"raw": 45200000, "formatted": "45,200,000 XAF"},
            "trial_balance_credit": {"raw": 45200000, "formatted": "45,200,000 XAF"},
            "posted_entries_count": {"raw": 2480, "formatted": "2,480 Entries"},
            "unreconciled_count": {"raw": 14, "formatted": "14 Items"},
            "ar_aging": {
                "current": "5,400,000 XAF",
                "days_30": "1,200,000 XAF",
                "days_60": "650,000 XAF",
                "days_90_plus": "250,000 XAF",
                "total_overdue": "900,000 XAF",
            },
            "ap_aging": {
                "current": "3,800,000 XAF",
                "days_30": "950,000 XAF",
                "days_60": "400,000 XAF",
                "days_90_plus": "150,000 XAF",
                "total_overdue": "550,000 XAF",
            },
        }
        res = generate_report_tool(
            tenant_id=self.tenant_id,
            report_type="accounting",
            report_data=accounting_data,
            custom_content="""## General Ledger & Reconciliation Audit
Trial balance balances perfectly at **45.2M XAF** across all posted subledger and GL accounts.""",
        )
        self.assertEqual(res["status"], "success")
        reports_generated["accounting"] = res

        # ── 12. General Intelligence Report ───────────────────────────────────
        general_data = {
            "revenue": {"raw": 12500000, "formatted": "12,500,000 XAF"},
            "net_profit": {"raw": 2480000, "formatted": "2,480,000 XAF"},
            "health_score": {"raw": 86, "formatted": "86/100"},
            "cash_balance": {"raw": 5400000, "formatted": "5,400,000 XAF"},
            "accounts_receivable": {"raw": 7500000, "formatted": "7,500,000 XAF"},
            "accounts_payable": {"raw": 5300000, "formatted": "5,300,000 XAF"},
            "trend_data": [
                {"period": "Jan", "revenue": 1800000, "expenses": 1400000, "net_profit": 400000},
                {"period": "Feb", "revenue": 2000000, "expenses": 1500000, "net_profit": 500000},
                {"period": "Mar", "revenue": 2200000, "expenses": 1600000, "net_profit": 600000},
            ],
        }
        res = generate_report_tool(
            tenant_id=self.tenant_id,
            report_type="general",
            report_data=general_data,
            custom_content="""## Executive Intelligence Snapshot
Summary of operational indicators across sales, profitability, liquidity, and asset utilization.""",
        )
        self.assertEqual(res["status"], "success")
        reports_generated["general"] = res

        # ── 13. Health Report (Legacy Template) ───────────────────────────────
        res = generate_report_tool(
            tenant_id=self.tenant_id,
            report_type="health",
            custom_content="""## Enterprise Health & Vital Signs
Executive review of primary operational ratios, liquidity buffers, and enterprise scorecards.""",
        )
        self.assertEqual(res["status"], "success")
        reports_generated["health"] = res

        # ── Verify All 13 Files Exist On Disk with Positive Size ─────────────
        self.assertEqual(len(reports_generated), 13)
        for r_type, report_res in reports_generated.items():
            fn = report_res["filename"]
            file_path = self.reports_dir / fn
            self.assertTrue(file_path.exists(), f"Report {r_type} file {fn} does not exist")
            size = file_path.stat().st_size
            self.assertGreater(size, 1000, f"Report {r_type} file {fn} is too small: {size} bytes")
            print(f"[SUCCESS] Generated {r_type.upper():<20} -> {fn} ({size:,} bytes)")
