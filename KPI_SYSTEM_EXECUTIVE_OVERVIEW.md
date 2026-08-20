# The KPI System — Complete Guide
### For Non-Technical Readers and New Team Members

---

## What Is This Document?

This document explains everything about the **KPI (Key Performance Indicators) system** — the part of the platform that answers the question: *"How is our business doing?"*

You do not need any programming knowledge to understand this guide. Every concept is explained from first principles.

---

## Part 1: What the KPI System Does

### The Everyday Analogy

Imagine you run a group of retail stores across multiple countries. Every day, thousands of things happen:

- Customers buy products (creating **sales orders**)
- You pay suppliers for goods (creating **purchase orders** and **vendor bills**)
- Products move in and out of warehouses (creating **stock movements**)
- Customers pay invoices (some on time, some late)
- Banks process payments in different currencies (USD, EUR, XAF, etc.)

All of this raw activity generates tens of thousands of database records. The KPI system's job is to **read all of those records and distill them into clear, actionable numbers** that executives and managers can use to make decisions.

### What It Produces

When someone opens the executive dashboard or makes an API request to `/api/v1/kpi/overview`, the system returns a complete financial snapshot:

| Category | What You See | Business Question It Answers |
|:---|:---|:---|
| **Revenue** | Total money earned from customer orders | *How much did we sell?* |
| **Expenses** | Total money spent on supplier purchases | *How much did we spend?* |
| **Profit** | Revenue minus Expenses | *Are we making money?* |
| **Gross Margin** | Profit as a percentage of Revenue | *How profitable are our products?* |
| **Order Count** | Number of completed sales orders | *How active is our business?* |
| **Average Order Value** | Revenue divided by Order Count | *How much does a typical customer spend?* |
| **Net Working Capital** | Current Assets minus Current Liabilities | *Can we pay our short-term debts?* |
| **Inventory Value** | Dollar value of goods in warehouses | *How much capital is tied up in stock?* |
| **Dead Stock** | Products sitting unsold for 90+ days | *What stock is wasting money?* |
| **Receivables Aging** | How late customers are paying invoices | *Who owes us money, and how overdue?* |
| **Currency Exposure** | Impact of exchange rate changes | *Are foreign currencies helping or hurting us?* |

---

## Part 2: How Date Filtering Works

### The Two Types of Business Numbers

This is the single most important concept to understand. Every business metric falls into one of two categories:

#### Type 1: "Flow" Metrics — Activity Over a Period

These measure **what happened** between two dates. Like a river — you measure how much water flowed past a point during a period.

**Examples:**
- Revenue earned between January 1 and March 31
- Number of orders placed in February
- Expenses incurred this month

**How the system calculates them:** It adds up all sales/purchases whose dates fall **between** `date_from` and `date_to`.

#### Type 2: "Snapshot" Metrics — State at a Moment

These measure **what the situation looked like** on one specific day. Like a photograph — you capture the state at a single point in time.

**Examples:**
- How much cash was in the bank on December 31?
- How much inventory was in the warehouse on June 30?
- Which invoices were unpaid as of March 31?

**How the system calculates them:** It adds up all transactions recorded **on or before** a cutoff date (which the system calls `as_of_date`, and which equals `date_to` when you provide it).

### Visual Explanation

```
Timeline: ──────────────────────────────────────────────────►

          date_from                              date_to
             │                                     │
             │◄──── Flow metrics (Revenue, ────────►│
             │      Expenses, Orders) are           │
             │      summed BETWEEN these dates      │
             │                                     │
             │                                     ● Snapshot metrics (Cash,
             │                                       Inventory, Unpaid Bills)
             │                                       are measured AS OF this
             │                                       single date
```

### What Happens When You Don't Provide Dates?

| Scenario | Flow Metrics | Snapshot Metrics |
|:---|:---|:---|
| No dates provided | All-time totals | Today's live state |
| Only `date_from` | From that date forward | As of today |
| Only `date_to` | All time up to that date | As of `date_to` |
| Both provided | Between the two dates | As of `date_to` |

---

## Part 3: The Problem We Fixed

### What Was Broken Before

Before our changes, the date filter only affected **some** of the numbers. Here is specifically what was wrong:

#### Problem 1: Inventory Value Was Frozen

When you asked: *"Show me the dashboard for the year 2025"*, the system correctly calculated 2025's revenue and expenses. But for inventory, it looked at **today's live warehouse shelves** (which showed $2.62 Billion worth of stock — the current 2026 value). It did this regardless of what dates you selected.

**Result:** Inventory Value showed the same $2.62 Billion whether you picked 2024, 2025, or 2026.

#### Problem 2: Net Working Capital Never Changed

Net Working Capital is calculated as:

```
Net Working Capital = (Cash + Unpaid Customer Invoices + Inventory) − (Unpaid Vendor Bills + Other Debts)
```

Since Inventory made up about 85% of the total assets, and Inventory was frozen (see Problem 1), the Working Capital number barely changed no matter what date range you selected.

#### Problem 3: Customer Aging Reports Included Future Invoices

When you asked: *"Show me overdue customer invoices as of December 31, 2025"*, invoices created in January 2026 were still appearing in the report — even though those invoices didn't exist yet on December 31, 2025.

#### Problem 4: Currency Exposure Ignored Dates Entirely

The foreign currency risk calculation looked at **all open invoices across all time**, regardless of your date selection. It also counted realized exchange gains/losses from the entire history of the company.

#### Problem 5: Redundant Parameter Names

Some endpoints accepted `start_date` and `end_date`, while others used `date_from` and `date_to`. This was confusing and inconsistent.

### What We Fixed

| Problem | Before | After |
|:---|:---|:---|
| **Inventory Value** | Always showed today's live warehouse stock | Calculates historical stock value by "replaying" all warehouse movements up to the selected date |
| **Net Working Capital** | Frozen — didn't respond to date changes | All components (Cash, Receivables, Inventory, Payables, Liabilities) are evaluated as of `date_to` |
| **Customer Aging** | Included invoices from the future | Excludes any invoice created after the report date |
| **Currency Exposure** | Ignored date filters | Unrealized FX only counts invoices open on `date_to`; Realized FX only counts entries within `date_from` to `date_to` |
| **Parameter Names** | Mixed `start_date`/`end_date` with `date_from`/`date_to` | All endpoints use only `date_from` and `date_to` |

### Proof That It Works

After the fix, querying different periods now produces different (correct) results:

| Period | Net Working Capital | Cash | Customer Invoices | Inventory | Vendor Bills |
|:---|---:|---:|---:|---:|---:|
| **End of 2024** | **4,760,595,347** | 126,637,164 | 288,099,519 | 4,475,738,434 | 129,879,770 |
| **Mid 2025** | **5,475,265,130** | −15,924,837 | 375,895,001 | 5,333,827,735 | 218,532,769 |
| **End of 2025** | **6,205,865,548** | −30,734,288 | 403,916,254 | 6,108,204,873 | 275,521,291 |
| **Jan 2026** | **6,197,483,674** | −52,588,906 | 412,348,054 | 6,113,284,217 | 275,559,691 |
| **Feb 2026** | **6,249,442,963** | −39,868,409 | 422,473,555 | 6,148,458,211 | 281,620,393 |
| **Mar 2026** | **6,249,338,197** | −48,503,729 | 432,796,132 | 6,164,906,017 | 299,860,223 |
| **Apr 2026** | **6,475,284,774** | 157,331,528 | 437,353,883 | 6,180,459,586 | 299,860,223 |
| **May 2026** | **6,318,586,114** | −60,481,388 | 446,869,684 | 6,321,591,599 | 389,393,781 |
| **Jun 2026** | **6,532,457,397** | 44,222,912 | 480,833,696 | 6,396,794,569 | 389,393,781 |

> **Note:** If you select July or August 2026 and see the same numbers as June, that is correct — the database has no transactions recorded after June 23, 2026 (the most recent data sync). Snapshot metrics show the latest known state, so they remain at the June 2026 level until new data arrives.

---

## Part 4: Every KPI Module Explained

### Module 1: Revenue, Expenses, and Profit

**Where it appears:** The top cards on the dashboard

**What it calculates:**

- **Revenue**: The `amount_total` field from all confirmed/completed Sales Orders whose `date_order` falls within the selected date range.
- **Expenses**: The `amount_total` field from all confirmed/completed Purchase Orders whose `date_order` falls within the selected date range.
- **Profit**: Revenue minus Expenses.
- **Gross Margin %**: How much of each dollar of revenue is retained after direct product costs. For example, a 45% gross margin means the company keeps $0.45 of every $1 sold.

**The "dashboard cards"** (Today / Month / Year) are always evaluated relative to the `date_to` date. So if `date_to` is March 15, 2026:
- "Today" shows March 15, 2026
- "Month" shows all of March 2026
- "Year" shows all of 2026

**Period-over-period comparison:** When both `date_from` and `date_to` are provided, the system automatically calculates the same-length previous period and shows:
- `previous_value`: What the metric was during the prior period
- `change_pct`: The percentage increase or decrease

*Example:* If you select February 1–28, 2026 (28 days), the system automatically compares against January 4–31, 2026 (the preceding 28 days) and reports something like: Revenue $50M (+12.3% vs previous).

---

### Module 2: Net Working Capital (NWC) and Financial Health

**Where it appears:** The "Net Working Capital" card on the dashboard

**What it is:** Net Working Capital tells you whether the company can pay its short-term obligations. It is the most important measure of financial survival.

**The formula:**

```
Net Working Capital = Current Assets − Current Liabilities

Current Assets = Cash in Bank
               + Unpaid Customer Invoices (what customers owe you)
               + Warehouse Inventory Value

Current Liabilities = Unpaid Vendor Bills (what you owe suppliers)
                    + Accrued Expenses
                    + Short-Term Debt
                    + Other Current Liabilities
```

**How each piece is calculated (after our fix):**

| Component | Data Source | Date Filter Applied |
|:---|:---|:---|
| **Cash** | General ledger entries with account type `asset_cash` | Only entries with posting date ≤ `date_to` |
| **Customer Invoices (AR)** | Posted outgoing invoices that are not fully paid | Only invoices with date ≤ `date_to` |
| **Inventory** | Historical stock movements (see Module 3 below) | Only movements completed on or before `date_to` |
| **Vendor Bills (AP)** | Posted incoming invoices that are not fully paid | Only bills with date ≤ `date_to` |
| **Accrued Expenses** | Liability ledger entries matching configured account prefixes | Only entries with posting date ≤ `date_to` |
| **Short-Term Debt** | Liability ledger entries matching configured account prefixes | Only entries with posting date ≤ `date_to` |
| **Other Liabilities** | Remaining liability ledger entries | Only entries with posting date ≤ `date_to` |

**Health indicators the system reports:**

| Metric | Formula | Meaning |
|:---|:---|:---|
| **Current Ratio** | Current Assets ÷ Current Liabilities | ≥ 1.5 is "Healthy", 1.0–1.49 is "Warning", < 1.0 is "Critical" |
| **Quick Ratio** | (Cash + Customer Invoices) ÷ Current Liabilities | Same as Current Ratio but excludes Inventory — measures ability to pay debts without selling stock |

**Company breakdown:** Each subsidiary company gets its own independent Working Capital calculation using the exact same date-bounded logic, so you can see which branches are healthy and which are struggling.

---

### Module 3: Inventory Valuation and Warehouse Risk

**Where it appears:** The "Inventory Value" and "Inventory Risk" sections

#### How Historical Inventory Valuation Works

This was the most complex fix. When no date filter is provided, the system reads the live `StockQuant` table (which is the physical count of goods currently in the warehouse). But when dates are provided, the system "rewinds time" using a three-step fallback:

**Step 1 — Stock Movement Replay (Primary Method):**
The system reads every completed warehouse movement (`StockMove` with `state = 'done'`) dated on or before `date_to`. For each product, it calculates:

```
Net Quantity = (All goods received into warehouses) − (All goods shipped out of warehouses)
Inventory Value = Net Quantity × Product Unit Cost
```

**Step 2 — General Ledger Fallback:**
If no stock movements are found, the system looks at accounting ledger entries tagged as `asset_current` (which is how accounting systems track inventory value) dated on or before `date_to`.

**Step 3 — Live Warehouse Fallback:**
If the requested date is today or in the future, and neither of the above methods produced results, the system falls back to the live physical warehouse count.

#### Inventory Risk Metrics

| Metric | What It Means | How It's Evaluated |
|:---|:---|:---|
| **Committed Stock %** | Percentage of warehouse stock already reserved for pending customer orders | Live warehouse data only (not historical) |
| **Low Stock Count** | Number of products with fewer than 5 units remaining | Live warehouse data only |
| **Expiring Soon** | Number of product lots/batches expiring within 30 days | Live warehouse data only |
| **Dead Stock Count** | Products in the warehouse that have had zero sales in the last 90 days | When historical: evaluated relative to the 90 days before `date_to` |
| **Dead Stock Rate %** | Dead Stock Count ÷ Total Unique Products × 100 | Same as above |

> **Why some metrics are "Live only":** Committed Stock (reservations), Low Stock (threshold alerts), and Expiring Soon (lot expiration dates) are operational signals about what needs attention **right now**. They are not meaningful for historical dates because the point of these alerts is to trigger immediate action.

---

### Module 4: Receivables Aging (Customer Debt Analysis)

**Where it appears:** `/api/v1/kpi/receivables-aging` and `/api/v1/kpi/receivables-aging/detail`

**What it does:** Shows how much money customers owe the company, broken down by how late their payments are.

**The aging buckets:**

| Bucket | Meaning | Typical Action |
|:---|:---|:---|
| **Current** | Invoice is not yet due (still within payment terms) | No action needed |
| **1–30 Days Overdue** | Slightly past due | Send a payment reminder |
| **31–60 Days Overdue** | Moderately late | Follow-up phone call |
| **61–90 Days Overdue** | Seriously late | Escalate to management |
| **90+ Days Overdue** | High risk of becoming bad debt | Legal action / write-off consideration |

**What we fixed:** The system now excludes any invoice whose `date` is after the report's reference date. Overdue days are calculated relative to the reference date, not today's calendar date. This means:

- Querying as of Dec 31, 2025: Only invoices created on or before Dec 31, 2025 appear. An invoice due Nov 30, 2025 shows as "31–60 days overdue" (31 days late as of Dec 31).
- Same invoice queried as of Jan 31, 2026: Shows as "61–90 days overdue" (62 days late as of Jan 31).

**The detail endpoint** (`/receivables-aging/detail`) lets you drill down into a specific bucket and see the individual invoices — including the customer's name, contact information, invoice amount, due date, and how many days overdue.

---

### Module 5: Multi-Currency and Foreign Exchange (FX) Exposure

**Where it appears:** `/api/v1/kpi/currency-impact`

**What it does:** For companies doing business in multiple currencies, exchange rate movements create financial risk. This module quantifies that risk.

**What it reports:**

| Section | What It Shows |
|:---|:---|
| **Currency Revenue Breakdown** | Percentage of total revenue from each currency (e.g., 60% XAF, 25% USD, 15% EUR) |
| **Exchange Rates** | Current conversion rates between each foreign currency and your base reporting currency |
| **Unrealized FX Impact** | Estimated gain/loss on unpaid foreign currency invoices if exchange rates have moved since the invoice was created |
| **Realized FX Impact** | Actual exchange gains/losses that were permanently recorded in the accounting system when foreign currency invoices were paid |

**What we fixed:**

- **Unrealized FX:** Now only counts invoices that were open (unpaid) on or before `date_to`. Previously it included all open invoices regardless of date.
- **Realized FX:** Now only counts exchange difference entries posted between `date_from` and `date_to`. Previously it summed the entire history.

---

### Module 6: Additional Analytics Endpoints

These endpoints provide deeper analysis. All of them accept `date_from`, `date_to`, `tenant_ids`, `company_ids`, and `base_currency`:

| Endpoint | What It Shows |
|:---|:---|
| **`/kpi/top-products`** | Best-selling products ranked by total revenue, with quantity sold and margin |
| **`/kpi/bottom-products`** | Worst-selling products (same data, sorted ascending) |
| **`/kpi/products/{id}/detail`** | Deep dive into a single product: total sales, revenue, margin, and a list of every sales order line |
| **`/kpi/top-customers`** | Most valuable customers ranked by total purchase volume |
| **`/kpi/customers/{id}/detail`** | Deep dive into a single customer: contact info and full order history with receipt-level breakdown |
| **`/kpi/fast-moving-products`** | Products with the highest sales velocity (quantity sold per time period) |
| **`/kpi/category-performance`** | Revenue and profit margins grouped by product category |
| **`/kpi/trends`** | Monthly revenue and expense trends over the selected period |
| **`/kpi/revenues`** | Paginated list of individual sales orders within the date range |
| **`/kpi/revenues/today`** | Today's sales orders |
| **`/kpi/revenues/monthly`** | This month's sales orders |
| **`/kpi/revenues/yearly`** | This year's sales orders |
| **`/kpi/expenses`** | Paginated list of individual purchase orders within the date range |
| **`/kpi/expenses/today`** | Today's purchase orders |
| **`/kpi/expenses/monthly`** | This month's purchase orders |
| **`/kpi/expenses/yearly`** | This year's purchase orders |
| **`/kpi/profits`** | Daily profit breakdown (revenue minus expenses per day) |

---

### Module 7: Multi-Tenant and Multi-Company Filtering

**What it is:** The platform supports two levels of organizational separation:

- **Tenant**: A completely separate organization/business. Different tenants never share data. (Think: two unrelated companies using the same software.)
- **Company**: A subsidiary within a tenant. Multiple companies under the same tenant can be analyzed together or separately. (Think: a parent corporation with regional branches.)

**Every single KPI endpoint** accepts these optional filters:

| Parameter | Purpose | Example |
|:---|:---|:---|
| `tenant_ids` | Restrict results to specific tenants | `tenant_ids=abc-123,def-456` |
| `company_ids` | Restrict results to specific subsidiary companies | `company_ids=26,27` |
| `base_currency` | Convert all monetary values into a single reporting currency | `base_currency=USD` |

**Currency conversion** works using a live exchange rate table synced from the ERP system. When you set `base_currency=USD`, every amount — regardless of whether the original transaction was in EUR, XAF, or GBP — is automatically converted to USD using the most recent exchange rates.

---

## Part 5: Complete API Reference

### Standardized Parameters

All endpoints use these consistent parameter names:

| Parameter | Type | Description | Example |
|:---|:---|:---|:---|
| `date_from` | Date string | Start of the reporting period | `2026-01-01` |
| `date_to` | Date string | End of the reporting period / snapshot cutoff | `2026-03-31` |
| `base_currency` | 3-letter code | Target currency for all monetary values | `USD`, `EUR`, `XAF` |
| `tenant_ids` | Comma-separated UUIDs | Filter to specific organizations | `abc-123,def-456` |
| `company_ids` | Comma-separated integers | Filter to specific subsidiary companies | `26,27` |

### Endpoint Summary

| Method | Path | Purpose |
|:---|:---|:---|
| `GET` | `/api/v1/kpi/overview` | Complete executive dashboard |
| `GET` | `/api/v1/kpi/summary` | Lightweight version of overview |
| `GET` | `/api/v1/kpi/trends` | Monthly revenue/expense trend lines |
| `GET` | `/api/v1/kpi/top-products` | Best-selling products |
| `GET` | `/api/v1/kpi/bottom-products` | Worst-selling products |
| `GET` | `/api/v1/kpi/products/{id}/detail` | Single product deep dive |
| `GET` | `/api/v1/kpi/top-customers` | Highest-value customers |
| `GET` | `/api/v1/kpi/customers/{id}/detail` | Single customer deep dive |
| `GET` | `/api/v1/kpi/receivables-aging` | Customer debt aging summary |
| `GET` | `/api/v1/kpi/receivables-aging/detail` | Individual invoices in an aging bucket |
| `GET` | `/api/v1/kpi/fast-moving-products` | Fastest-selling products |
| `GET` | `/api/v1/kpi/category-performance` | Performance by product category |
| `GET` | `/api/v1/kpi/currency-impact` | Multi-currency exposure and FX impact |
| `GET` | `/api/v1/kpi/revenues` | Itemized sales orders |
| `GET` | `/api/v1/kpi/revenues/today` | Today's sales orders |
| `GET` | `/api/v1/kpi/revenues/monthly` | This month's sales orders |
| `GET` | `/api/v1/kpi/revenues/yearly` | This year's sales orders |
| `GET` | `/api/v1/kpi/expenses` | Itemized purchase orders |
| `GET` | `/api/v1/kpi/expenses/today` | Today's purchase orders |
| `GET` | `/api/v1/kpi/expenses/monthly` | This month's purchase orders |
| `GET` | `/api/v1/kpi/expenses/yearly` | This year's purchase orders |
| `GET` | `/api/v1/kpi/profits` | Daily/periodic profit breakdown |

---

## Part 6: Glossary

| Term | Definition |
|:---|:---|
| **Accounts Payable (AP)** | Money the company owes to its suppliers for goods or services already received but not yet paid for |
| **Accounts Receivable (AR)** | Money owed to the company by its customers for goods or services already delivered but not yet paid for |
| **As-Of Date** | The specific calendar date used to evaluate snapshot metrics. Usually equals `date_to`. |
| **Base Currency** | The currency in which all values are expressed. Set via the `base_currency` parameter. Default is XAF. |
| **Current Assets** | Assets that can be converted to cash within 12 months: Cash + Customer Invoices + Inventory |
| **Current Liabilities** | Debts due within 12 months: Supplier Bills + Accrued Expenses + Short-Term Loans |
| **Current Ratio** | Current Assets ÷ Current Liabilities. A ratio of 1.5 or above means the company can comfortably pay its debts. |
| **Dead Stock** | Products physically present in the warehouse that have not generated a single sale in 90 days. Dead stock ties up capital unproductively. |
| **Flow Metric** | A metric measured over a time range (e.g., total revenue between two dates) |
| **Gross Margin** | (Revenue − Cost of Goods Sold) ÷ Revenue × 100. Measures how much profit each dollar of sales generates before overhead costs. |
| **Net Working Capital** | Current Assets minus Current Liabilities. A positive number means the company can pay its short-term debts. |
| **Quick Ratio** | (Cash + Receivables) ÷ Current Liabilities. Like the Current Ratio but excludes Inventory — answers "Can we pay our debts without selling stock?" |
| **Realized FX** | An exchange rate gain or loss that has been permanently finalized because a foreign-currency invoice was fully paid and the money was deposited in the bank. This is a real, locked-in profit or loss. |
| **Snapshot Metric** | A metric measured at a single point in time (e.g., bank balance as of December 31) |
| **StockMove** | A database record representing a physical movement of goods — either into a warehouse (receiving) or out of a warehouse (shipping) |
| **StockQuant** | A database record representing the live, current physical count of a product in a specific warehouse location |
| **Tenant** | An independent organization on the platform. Tenants are completely isolated from each other. |
| **Unrealized FX** | An estimated exchange rate gain or loss on foreign-currency invoices that have not yet been paid. This is a "paper" gain or loss that could change before the invoice is settled. |
