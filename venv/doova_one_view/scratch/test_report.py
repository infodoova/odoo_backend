import os
import sys
from pathlib import Path
from dotenv import load_dotenv
import django

project_root = Path("c:/Users/PC/Desktop/doova_one_view/odoo_backend/venv/doova_one_view")
load_dotenv(project_root / ".env")
sys.path.insert(0, str(project_root))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'doova_one_view.settings')
django.setup()

from doova_one_view.api.agent.tools_refactored.reporting_v2 import generate_report_tool

custom_content = """
Here is the complete **Financial & Operational Health Report** for **SUPERNOVA, S.L. — YTD 2026 (January 1 – July 14, 2026)**. The branded PDF is ready for download at the link below. Full executive analysis follows.

---

# 🏢 SUPERNOVA, S.L. — COMPREHENSIVE FINANCIAL & OPERATIONAL HEALTH REPORT
### Period: YTD 2026 | January 1 – July 14, 2026 | Currency: XAF

---

## 🔴 EXECUTIVE SUMMARY

| Indicator | Value | Status |
|---|---|---|
| **Composite Business Health Score** | **69.5 / 100** | 🟡 Stable |
| **YTD Net Profit** | **–XAF 19.4M** | 🔴 Net Loss |
| **Gross Margin** | **38.91%** | 🟡 Below Service Benchmark |
| **Current Ratio** | **3.85x** | 🟢 Excellent |
| **Debt-to-Equity** | **0.45x** | 🟢 Conservative |
| **AR Overdue Ratio** | **100%** | 🔴 Critical |
| **Collections Health Score** | **0 / 25** | 🔴 Failing |
| **Anomaly Risk Level** | **High** | 🔴 Requires Investigation |

> **CFO Summary:** SUPERNOVA, S.L. presents a structurally sound balance sheet with excellent liquidity and conservative leverage, but is bleeding at the bottom line in 2026 YTD. The core threats are a **total AR collections failure** (100% of receivables overdue), a **net operating loss of XAF 19.4M**, a **balance sheet integrity imbalance of XAF 63.2M**, and **high-risk journal entry anomalies** that demand immediate audit attention.

---

## 1. 📊 PROFIT & LOSS — YTD 2026

| Line Item | Amount (XAF) | Margin % |
|---|---|---|
| **Total Income** | 139,401,140 | — |
| Cost of Goods Sold (COGS) | 85,158,338 | 61.09% of revenue |
| **Gross Profit** | **54,242,802** | **38.91%** |
| Operating Expenses | 37,972,257 | 27.24% of revenue |
| **EBIT** | **16,270,545** | **11.67%** |
| Other Expenses / Non-Operating | 35,680,744 | — |
| **Net Profit / (Loss)** | **–19,410,199** | **–13.92%** |

### Profitability Assessment
- **Gross Margin at 38.91%** — For a service-based business, this falls **significantly below** the 60–80% benchmark for service/SaaS firms. This suggests SUPERNOVA carries substantial product/COGS-linked costs inconsistent with a pure service model, or that service pricing is under pressure.
- **Net Margin at –13.92%** — Firmly in **critical territory** (benchmark: Healthy >= 5%). The swing from EBIT of +XAF 16.3M to a net loss of –XAF 19.4M implies **XAF 35.7M in non-operating costs** (interest, write-offs, or one-time charges) eroding operational gains entirely.
- **Sales Revenue (Orders):** XAF 110.7M from **91 orders** at an avg. order value of **XAF 1.217M** — diverging from Total Income of XAF 139.4M, suggesting additional non-sales income streams.

---

## 2. 💰 SALES PERFORMANCE & TREND — YTD 2026

| Month | Revenue (XAF) | Orders |
|---|---|---|
| January 2026 | 4,354,201 | 13 |
| February 2026 | 26,697,895 | 23 |
| March 2026 | 17,941,977 | 9 |
| April 2026 | 4,515,251 | 6 |
| May 2026 | 10,987,001 | 12 |
| June 2026 | 46,253,012 | 28 |
| **YTD Total** | **110,749,337** | **91** |

### Key Observations
- **January and April were severely depressed months** (XAF 4.35M and XAF 4.5M respectively) — among the weakest in the company's 4-year history.
- **June 2026 saw a strong recovery surge** (+XAF 35.3M vs May, or a **+224% MoM jump**), which signals possible seasonal concentration or a large contract win. This is encouraging but insufficient to offset prior months.
- **2026 is dramatically underperforming vs. 2025** — H1 2025 revenue totalled approx. XAF 224M vs H1 2026 at ~XAF 110.7M, a **decline of approximately 51% YoY**.
- Peak historical months (Aug 2024: XAF 247M; Oct 2025: XAF 207M) demonstrate the company is capable of significantly higher throughput — the current run rate represents a structural slowdown that needs investigation.

---

## 3. 🏆 TOP REVENUE-GENERATING PRODUCTS (All-Time)

| Rank | Product | Revenue (XAF) | Units Sold |
|---|---|---|---|
| 1 | Television Nasco 65" 4K | 420,528,869 | 1,457 |
| 2 | Television TCL 43" | 276,082,850 | 778 |
| 3 | Television TCL 65" | 222,569,538 | 530 |
| 4 | Bolt Cutter 750mm | 22,015,762 | 59 |
| 5 | Bolt Cutter 600mm | 13,579,853 | 30 |
| 6 | Insulated Safety Boots (42) | 11,141,411 | 1 |
| 7 | Test Pencil 4×190mm | 8,351,172 | 68 |
| 8 | Spirit Level 80cm | 6,596,410 | 68 |
| 9 | Headlamp (THL013AAA5) | 6,553,770 | 5 |

> ⚠️ **Note:** Despite being classified as a Service-Based company, **television sets dominate revenue**. This confirms a **hybrid product/service** commercial model in practice. Management should review business model classification as it affects margin benchmarks, tax treatment, and inventory strategy.

---

## 4. 🏦 BALANCE SHEET SNAPSHOT

| Category | Amount (XAF) |
|---|---|
| **Current Assets** | 997,038,182,865 |
| Non-Current Assets | 31,280,169,247 |
| **Total Assets** | **1,028,318,352,112** |
| Current Liabilities | 480,394,702,354 |
| Non-Current Liabilities | 0 |
| **Total Liabilities** | **480,394,702,354** |
| **Total Equity** | **611,158,026,424** |

### ⚠️ INTEGRITY ALERT — BALANCE SHEET IMBALANCED
> **Assets (XAF 1,028.3B) ≠ Liabilities + Equity (XAF 1,091.6B)**
> **Imbalance: –XAF 63,234,376,666** — This is a **material accounting error** that must be investigated immediately. Possible causes: unposted journal entries, rounding accumulation, or erroneous equity adjustments. This correlates  with the anomalies detected below.

---

## 5. 📐 FINANCIAL RATIOS

| Ratio | Value | Benchmark | Status |
|---|---|---|---|
| **Current Ratio** | 3.85x | >= 1.5 = Good | 🟢 Excellent |
| **Quick Ratio** | 3.08x | >= 1.0 = Good | 🟢 Excellent |
| **Debt-to-Equity** | 0.45x | < 1.0 = Low Risk | 🟢 Conservative |
| **Return on Equity (ROE)** | 31.09% | >= 15% = Good | 🟢 Excellent |
| **Return on Assets (ROA)** | 17.82% | >= 8% = Good | 🟢 Excellent |
| **Gross Margin** | 37.78% | 60–80% (Service) | 🔴 Below Benchmark |
| **Net Margin** | 8.27% | >= 5% = Healthy | 🟡 Borderline |

> The ratio picture shows a **split personality**: the balance sheet is fortress-strong (liquidity, leverage, ROE all excellent), but the operating income statement is deteriorating (gross margin compressed, YTD net loss).

---

## 6. 💧 LIQUIDITY & WORKING CAPITAL

| Metric | Value (XAF) | Status |
|---|---|---|
| **Working Capital** | 834,074,576 | 🟢 Positive |
| **Working Capital Ratio** | 3.85x | 🟢 Strong |
| **Accounts Receivable** | 507,649,679 | — |
| **Accounts Payable** | 85,292,353 | — |
| **Net Cash Position (AR–AP)** | 422,357,326 | 🟢 Positive |
| **Total Overdue Exposure** | 592,942,032 | 🔴 Critical |
| **Liquidity Status** | Stable | 🟡 Watchlist |

---

## 7. 📬 ACCOUNTS RECEIVABLE AGING — 🔴 CRITICAL

| Aging Bucket | Amount (XAF) | % of Total AR |
|---|---|---|
| Current (0 days) | 0 | 0% |
| 1–30 Days | 2,582,478 | 0.5% |
| 31–60 Days | 29,684,535 | 5.8% |
| 61–90 Days | 202,500 | 0.04% |
| **90+ Days Overdue** | **475,180,166** | **🔴 93.6%** |
| **Total AR** | **507,649,679** | — |

### Top Overdue Customers
| Customer | Overdue Balance (XAF) |
|---|---|
| Issam Assaf | 570,054,626 |
| elisa | 530,965,377 |
| SR. RUBEN EBANG | 210,469,613 |
| AWADA Marina cell | 125,207,968 |
| MAHMOUD SHAAR-HH | 93,391,493 |

> 🚨 **93.6% of all AR is 90+ days overdue.** This is the single most urgent operational crisis. Five customers alone hold balances far exceeding total AR — indicating potential misclassification or intercompany transactions embedded in AR. Immediate collections intervention and ledger reconciliation are required.

---

## 8. 📤 ACCOUNTS PAYABLE AGING

| Aging Bucket | Amount (XAF) | % of Total AP |
|---|---|---|
| Current | 0 | 0% |
| 1–30 Days | 0 | 0% |
| 31–60 Days | 82,809,521 | 97.1% |
| 61–90 Days | 0 | 0% |
| **90+ Days** | **2,482,832** | **2.9%** |
| **Total AP** | **85,292,353** | — |

> AP is predominantly in the **31–60 day bucket** — manageable but requires monitoring to avoid slipping to 90+. The **DPO is within the optimal 30–45 day range**, though vendor exposure from overdue AP (100% ratio) should be monitored. Key vendors with large exposures include EMILIA MANGUE (XAF 814.7M) and ministro de transporte (XAF 545.3M) — these figures appear disproportionately large vs. AP totals and warrant ledger review.

---

## 9. 👥 CUSTOMER METRICS & RETENTION

| Metric | Value | Status |
|---|---|---|
| **Total Customers** | 90 | — |
| **Repeat Customers** | 33 | — |
| **Retention Rate** | 36.7% | 🔴 Low |
| **Churn Risk** | Medium | 🟡 Monitor |

### Revenue Concentration Risk 🔴
| Customer | Orders | Revenue (XAF) |
|---|---|---|
| Issam Assaf | 255 | 799,904,844 |
| elisa | 103 | 662,863,338 |
| SR. RUBEN EBANG | 11 | 210,469,613 |

> ⚠️ **Top 2 customers alone (Issam Assaf + elisa) represent XAF 1.46BB of lifetime revenue** — extreme concentration risk. Loss of either customer would be catastrophic. Retention rate of **36.7% is critically low** for a service business targeting recurring relationships. A structured customer success programme is urgently needed.

---

## 10. 📦 INVENTORY HEALTH

### Low Stock Alerts — 25 Items at Critical Levels
All 25 flagged items have **only 1 unit remaining**, across locations including Malabo, Maria Cano Stock, Semu Stock, and Sipopo Stock. Notable items:
- Hand Saw 400mm, Hydraulic Floor Jack, Scooters, Steel Measuring Tape, Safety Boots, Samsung Galaxy Note 20 Ultra, Lithium-Ion Battery Pack

### Inventory Efficiency
| Metric | Value | Benchmark | Status |
|---|---|---|---|
| **Total Inventory Value** | XAF 1,627,934,163 | — | — |
| **Turnover Ratio** | **0.0x** | > 8x = Excellent | 🔴 Stagnant |
| **Days on Hand** | N/A | < 45 days ideal | 🔴 Unmeasurable |
| **Efficiency Rating** | **Low** | — | 🔴 Dead Stock Risk |

> 🚨 **Zero inventory turnover** means XAF 1.63B in stock is generating **no sales movement** — this is capital completely immobilized. Immediate stock audit, clearance initiatives, and procurement freeze on slow movers are required. This is tying up working capital that could fund operations.

---

## 11. 🔍 AUDIT & ANOMALY DETECTION — 🔴 HIGH RISK

### Unbalanced Journal Entries
| Entry | Debit (XAF) | Credit (XAF) | Variance |
|---|---|---|---|
| 49784 | 1,952,120 | 11,000 | **–1,941,120** |
| 49787 | 10,500 | 100,000 | **–89,500** |
| 49786 | 11,000 | 10,500 | **–500** |

### Statistical Outliers (>3σ from Mean)
| Entry | Account | Amount (XAF) | Date |
|---|---|---|---|
| 50685 | JETOUR Invoices of Goods | 460,074,862 | 2025-11-27 |
| 50685 | JETOUR Cost of Goods Sold | –405,283,292 | 2025-11-27 |
| 82714 | Current Year Earning | 280,064,942 | 2025-01-01 |"""

try:
    generate_report_tool(tenant_id="4fa1b33d-870f-4681-a54e-52e9b12f6b99", custom_content=custom_content, company_id=1)
    print("Report generated successfully.")
except Exception as e:
    print(f"Error: {e}")
