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
# AR/AP Aging & Working Capital Analysis Report
**Prepared by:** Nexus Virtual CFO
**Report Date:** July 14, 2026
**Entity Scope:** All Companies (Consolidated)
**Currency:** XAF
**Business Model:** Service-Based

---

## Executive Summary

This report presents a consolidated analysis of Accounts Receivable (AR) aging — money owed to the business — and Accounts Payable (AP) aging — obligations owed to vendors and suppliers. The findings reveal **critical collection risk** concentrated in the 90+ day overdue bucket and a **fully overdue AP ledger** requiring immediate prioritization. The net cash position remains nominally positive at **XAF 740.9M**, but total overdue exposure across both sides is a substantial **XAF 1.22 billion**.

---

## Section 1: Accounts Receivable (AR) — Who Owes Us Money

### 1.1 AR Overview

| Metric | Value | Assessment |
|---|---|---|
| **Total AR Outstanding** | XAF 980.5M | — |
| **Overdue AR** | XAF 980.5M | 🔴 Critical |
| **Overdue Ratio** | 100% | 🔴 Critical (Benchmark: Healthy < 15%) |
| **Risk Level** | HIGH | Immediate Action Required |

> ⚠️ **100% of all outstanding receivables are overdue.** There is zero current (non-overdue) AR on the books. This is a severe collections health failure requiring immediate escalation.

---

### 1.2 AR Aging Bucket Breakdown

| Aging Bucket | Amount (XAF) | % of Total AR |
|---|---|---|
| Current (0 days) | 0 | 0.0% |
| 1–30 Days Overdue | 9,052,478 | 0.9% |
| 31–60 Days Overdue | 35,069,335 | 3.6% |
| 61–90 Days Overdue | 5,060,000 | 0.5% |
| **90+ Days Overdue** | **931,296,994** | **95.0%** |
| **TOTAL** | **980,478,807** | **100%** |

> 🔴 **CRITICAL: 95% of all receivables (XAF 931.3M) are 90+ days overdue.** This level of aging concentration signals systemic collection failures. Amounts this old carry significant write-off risk and potential bad debt expense exposure.

---

### 1.3 Top Overdue Customers — Priority Collections List

| Rank | Customer | Overdue Amount (XAF) | Priority |
|---|---|---|---|
| 1 | **STEFAN** | 963,325,822 | 🔴 URGENT |
| 2 | **elisa** | 707,839,570 | 🔴 URGENT |
| 3 | **Issam Assaf** | 681,879,922 | 🔴 URGENT |
| 4 | **Ventage** | 412,360,587 | 🔴 HIGH |
| 5 | **NOEMI ALOGO** | 269,740,000 | 🔴 HIGH |
| 6 | **SR. RUBEN EBANG** | 210,469,613 | 🟠 HIGH |
| 7 | **MAHMOUD SHAAR-HH** | 206,081,362 | 🟠 HIGH |
| 8 | **AWADA Marina cell** | 205,731,777 | 🟠 HIGH |
| 9 | **SOS** | 172,629,826 | 🟠 MEDIUM |
| 10 | **JOSE-FINA** | 136,861,503 | 🟠 MEDIUM |

> **Note on Customer Profile:** STEFAN, elisa, and Issam Assaf are also top revenue-generating customers. Issam Assaf alone accounts for **XAF 1.85B in lifetime revenue** across 1,234 orders, making their XAF 681.9M overdue balance both a major risk and a sensitive collections situation.

---

## Section 2: Accounts Payable (AP) — Who We Owe

### 2.1 AP Overview

| Metric | Value | Assessment |
|---|---|---|
| **Total AP Outstanding** | XAF 1,061.3M | — |
| **Overdue AP** | XAF 1,061.3M | 🔴 Critical |
| **Overdue Ratio** | 100% | 🔴 All payables are overdue |

> ⚠️ **100% of all outstanding payables are also overdue.** This indicates no invoices are being settled within terms across any vendor relationship.

---

### 2.2 AP Aging Bucket Breakdown

| Aging Bucket | Amount (XAF) | % of Total AP |
|---|---|---|
| Current (0 days) | 0 | 0.0% |
| 1–30 Days Overdue | 0 | 0.0% |
| 31–60 Days Overdue | 82,809,521 | 7.8% |
| 61–90 Days Overdue | 7,494,037 | 0.7% |
| **90+ Days Overdue** | **149,259,527** | **14.1%** |
| **TOTAL (Aging Buckets)** | **239,563,085** | **~22.6%** |
| **Total AP (Full Ledger)** | **1,061,316,224** | 100% |

> The aging buckets capture XAF 239.6M, which represents the most actively tracked overdue AP. The full AP ledger of XAF 1.06B includes longer-standing obligations spread across all vendor accounts.

---

### 2.3 Top Overdue Vendors — Priority Payment List

| Rank | Vendor | Overdue Amount (XAF) | Priority |
|---|---|---|---|
| 1 | **EMILIA MANGUE** | 1,348,449,563 | 🔴 URGENT |
| 2 | **CIRCLE TRAVEL** | 1,114,899,224 | 🔴 URGENT |
| 3 | **JUSTINA CUELLAR DIAZ** | 787,498,317 | 🔴 HIGH |
| 4 | **ministro de transporte** | 697,049,770 | 🔴 HIGH |
| 5 | **Sociam** | 593,610,130 | 🔴 HIGH |
| 6 | **Night Vision** | 517,141,101 | 🟠 HIGH |
| 7 | **ABDAMIS RODRIGUEZ** | 196,105,486 | 🟠 MEDIUM |
| 8 | **COMERCIAL CHAMPION** | 186,421,837 | 🟠 MEDIUM |
| 9 | **ELISEO EDJABUA** | 150,468,946 | 🟠 MEDIUM |
| 10 | **felisa wilson** | 141,200,000 | 🟠 MEDIUM |

> 🚨 The top two vendors alone (EMILIA MANGUE and CIRCLE TRAVEL) represent over **XAF 2.46B in overdue payables** — a concentration of supplier risk that could result in service disruptions, legal action, or damaged vendor relationships if not urgently addressed.

---

## Section 3: AR vs. AP Comparative Analysis

### 3.1 Net Position Summary

| | Accounts Receivable | Accounts Payable | Net |
|---|---|---|---|
| **Total Outstanding** | XAF 980.5M | XAF 1,061.3M | **-XAF 80.8M** (AP Exceeds AR) |
| **Overdue Amount** | XAF 980.5M | XAF 1,061.3M | Net Overdue Deficit |
| **Overdue %** | 100% | 100% | Both fully overdue |
| **90+ Day Concentration** | 95.0% | 14.1% (tracked) | AR far more aged |

**Cash Flow Net Position:** XAF 740.9M (Stable per liquidity model)
**Total Overdue Exposure (both sides):** XAF 1.22 Billion

### 3.2 Key Comparison Insights

1. **AR Aging is Far More Severe than AP:** While both ledgers are 100% overdue, AR has 95% of balances in the 90+ day bucket versus AP's 14.1% in tracked buckets. The business is waiting longer to collect than it is delaying payments.

2. **AP Exceeds AR by XAF 80.8M:** On a total outstanding basis, the company owes slightly more than it is owed, creating a **net payables deficit**. This compresses liquidity headroom.

3. **Vendor Exposure is Concentrated:** The top 6 vendors account for a combined overdue amount exceeding XAF 4.6B — well above the total AR outstanding. This suggests vendor ledger balances may include historical or accumulated payables not yet resolved.

4. **Working Capital Risk:** Zero current AR and zero current AP indicates no healthy, within-terms activity is being tracked. The entire working capital cycle is operating in arrears.

---

## Section 4: Customer Context & Concentration Risk

| Metric | Value | Assessment |
|---|---|---|
| Total Customers | 501 | Broad base |
| Repeat Customers | 247 (49.3%) | 🟡 Medium retention |
| Top 3 Customers' Revenue | ~XAF 3.79B | 🔴 High concentration |
| Churn Risk | Medium | Monitor closely |

- **Issam Assaf** (1,234 orders, XAF 1.85B revenue) is the single largest customer and also among the top overdue debtors. Any hardline collections approach must be balanced against relationship preservation.
- **STEFAN** (45 orders, XAF 962M revenue) has the largest individual overdue balance at XAF 963.3M — nearly matching total gross revenue from that customer. This is a red flag for potential bad debt.
- **elisa** (483 orders, XAF 976M revenue) shows a pattern of high order volume with XAF 707.8M overdue — collections engagement is essential.

---

## Section 5: Risk Assessment & Benchmarking

| Risk Area | Current Status | Benchmark | Rating |
|---|---|---|---|
| AR Overdue % | 100% | Healthy < 15% | 🔴 CRITICAL |
| AR 90+ Day Concentration | 95% | Should be minimal | 🔴 CRITICAL |
| AP Overdue % | 100% | Should maintain within-terms | 🔴 CRITICAL |
| Net AR/AP Position | -XAF 80.8M | AR should exceed AP | 🟠 WARNING |
| Customer Concentration | Top 3 = ~60%+ of AR | > 50% = High Risk | 🔴 HIGH RISK |
| Cash Flow Liquidity | Stable (XAF 740.9M net) | Positive | 🟢 STABLE |

---

## Section 6: Strategic Recommendations

### 🔴 Immediate Actions (0–30 Days)

1. **Launch Emergency Collections Drive:** Engage STEFAN (XAF 963.3M), elisa (XAF 707.8M), and Issam Assaf (XAF 681.9M) with formal demand letters and structured payment plans. These three accounts alone represent **XAF 2.35B in overdue receivables.**

2. **Initiate Vendor Payment Negotiations:** Engage EMILIA MANGUE and CIRCLE TRAVEL — combined XAF 2.46B in overdue payables — to negotiate payment schedules before vendor relationships deteriorate or legal claims are filed.

3. **Conduct Bad Debt Provisioning Review:** With 95% of AR in the 90+ day bucket (XAF 931.3M), the finance team should immediately assess which balances qualify for bad debt provisions under IFRS 9 expected credit loss (ECL) methodology.

### 🟠 Short-Term Actions (30–90 Days)

4. **Implement Credit Limits & Terms Enforcement:** No new credit should be extended to existing overdue customers without partial settlement. Introduce formal credit approval protocols.

5. **Restructure Vendor Payment Terms:** Negotiate extended DPO with top vendors to ease cash outflow while collections are pursued. Prioritize vendors with legal risk.

6. **AR Write-Off Analysis:** Identify balances that are unrecoverable (especially 90+ day accounts) and determine write-off eligibility to improve balance sheet accuracy.

### 🟢 Structural / Long-Term Actions (90+ Days)

7. **Automate AR Dunning Workflow:** Implement automated payment reminders at 15, 30, 45, and 60 days post-due to prevent future aging concentration.

8. **Monthly AR/AP Review Cadence:** Establish a monthly working capital review to track aging bucket migration and ensure no new 90+ day buildup occurs.

9. **Customer Diversification:** The top-3 customer concentration exceeding 60% of AR is a structural risk. Pursue new customer acquisition to reduce dependency.

---

## Appendix: Data Summary

| Item | Value |
|---|---|
| Report Date | July 14, 2026 |
| Total AR | XAF 980,503,172 |
| Total AP | XAF 1,061,316,224 |
| Net Position (AR–AP) | XAF -80,813,052 |
| Total Overdue Exposure | XAF 1,220,041,892 |
| AR 90+ Day Balance | XAF 931,296,994 |
| AP 90+ Day Balance (tracked) | XAF 149,259,527 |
| Total Customers | 501 |
| Retention Rate | 49.3% |
| Liquidity Status | Stable |
| Collections Risk | CRITICAL |
"""

try:
    generate_report_tool(tenant_id="4fa1b33d-870f-4681-a54e-52e9b12f6b99", custom_content=custom_content, company_id=None)
    print("Report generated successfully.")
except Exception as e:
    print(f"Error: {e}")
