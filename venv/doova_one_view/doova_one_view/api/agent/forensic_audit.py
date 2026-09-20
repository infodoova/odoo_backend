"""
Forensic integrity audit engine — CPA / internal-audit grade.

Upgrades over original implementation:
1. MATERIALITY FRAMEWORK. Derives overall materiality, performance materiality
   and a clearly-trivial threshold, and gates all findings and score deductions against them.
2. ASSERTION MAPPING. Each test is tied to the financial-statement assertion it
   addresses (existence, completeness, accuracy, cutoff, classification, rights).
3. ISA 240 JOURNAL ENTRY TESTING. Management override of controls is treated as a
   presumed significant risk, with an explicit high-risk JE criteria battery.
4. BENFORD'S LAW digit analysis with MAD conformity thresholds.
5. SEGREGATION OF DUTIES testing and formal control-deficiency classification
   (deficiency / significant deficiency / material weakness).
6. PRIORITY-SPECIFIC TEST BATTERIES. Each audit priority carries a real,
   named procedure list instead of a bare tool string.
7. MISSTATEMENT SCHEDULE. Factual, judgmental and projected misstatements are
   accumulated and compared against materiality — the actual audit conclusion.
8. DETERMINISTIC SCORING GUARD. Score, status and grade are reconciled in Python,
   with severity ceilings so a critical finding can never return "Verified".
9. Exact date windows computed server-side, including cutoff-testing sub-windows.

Original response keys (title, score, status, grade, alerts, findings, session_id)
are preserved verbatim. All new analytics are additive.
"""

from __future__ import annotations

import calendar
import uuid
from dataclasses import dataclass, field
from datetime import date as _date, datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple

from fastapi import HTTPException
from doova_one_view.api.agent.logger import log_error

# ==========================================================================
# 1. AUDIT POLICY CONSTANTS
# ==========================================================================

MATERIALITY_POLICY = """   Benchmark selection (choose ONE and justify it):
     - Profit-oriented, stable earnings ....... 5% of pre-tax income
     - Loss-making or volatile earnings ....... 0.5% - 1% of revenue
     - Asset-intensive / holding entity ....... 1% - 2% of total assets
     - Early stage / pre-profit ............... 1% - 2% of gross profit or equity
   Performance materiality = 75% of overall materiality (use 50% where control
     risk is assessed as high, e.g. prior-period restatements or SoD failures).
   Clearly trivial threshold = 5% of overall materiality.
     Findings below this threshold are NOT reported individually - aggregate them
     into a single summary line."""

PERFORMANCE_MATERIALITY_RATE = 0.75
CLEARLY_TRIVIAL_RATE = 0.05

BENFORD_FIRST_DIGIT = {
    1: 30.1, 2: 17.6, 3: 12.5, 4: 9.7, 5: 7.9,
    6: 6.7, 7: 5.8, 8: 5.1, 9: 4.6,
}
BENFORD_TABLE = "  ".join(f"{d}:{p}%" for d, p in BENFORD_FIRST_DIGIT.items())

JE_RISK_CRITERIA = """     - Manual entries to accounts that are normally system-generated
     - Entries posted outside business hours, on weekends, or on public holidays
     - Round-number entries (amounts ending in 000) above the clearly-trivial threshold
     - Entries sitting just below a known approval threshold (splitting indicator)
     - Entries posted on the last 3 days of the period or after the closing date
     - Entries with blank, generic, or single-character descriptions
     - Entries reversed within a short window after period end
     - Entries posted by users who rarely or never post journals
     - Seldom-used or unrelated account-pair combinations
     - Entries to suspense, clearing, or 'miscellaneous' accounts
     - One-sided entries, or entries where debit and credit counts are asymmetric"""

ASSERTIONS = (
    "existence / occurrence, completeness, accuracy / valuation, cutoff, "
    "classification, rights & obligations, presentation & disclosure"
)

DEFICIENCY_CLASSES = """     - "material_weakness": a reasonable possibility that a material misstatement
       would not be prevented or detected on a timely basis.
     - "significant_deficiency": less severe than a material weakness, but important
       enough to merit attention by those charged with governance.
     - "control_deficiency": a control does not allow management or employees, in the
       normal course of their duties, to prevent or detect misstatements timely.
     - "observation": no control failure; efficiency or hygiene improvement only."""

SCORE_BANDS: Tuple[Tuple[int, int, str, str], ...] = (
    (90, 100, "Verified", "AA"),
    (75, 89, "Attention Needed", "A"),
    (50, 74, "Issues Found", "B"),
    (0, 49, "Critical", "C"),
)

SEVERITY_SCORE_CEILING: Dict[str, int] = {
    "critical": 58,
    "warning": 88,
    "review": 100,
}
DEFICIENCY_SCORE_CEILING: Dict[str, int] = {
    "material_weakness": 52,
    "significant_deficiency": 74,
    "control_deficiency": 89,
    "observation": 100,
}


# ==========================================================================
# 2. AUDIT PLANS
# ==========================================================================

@dataclass(frozen=True)
class AuditPlan:
    key: str
    tools: str
    focus: str
    pillar_weights: Dict[str, int]
    procedures: str


PILLARS = (
    "ledger_integrity",
    "subledger_reconciliation",
    "tax_compliance",
    "transaction_integrity",
    "control_environment",
)

_DEFAULT_WEIGHTS = {
    "ledger_integrity": 25,
    "subledger_reconciliation": 20,
    "tax_compliance": 20,
    "transaction_integrity": 20,
    "control_environment": 15,
}

AUDIT_PLANS: Dict[str, AuditPlan] = {
    "Duplicate Detection": AuditPlan(
        key="Duplicate Detection",
        tools="detect_anomalies, journal_audit, trial_balance, payment_reconciliation",
        focus="Duplicate payment and double-booking exposure, with recovery quantification.",
        pillar_weights={**_DEFAULT_WEIGHTS, "transaction_integrity": 35,
                        "control_environment": 20, "tax_compliance": 10},
        procedures="""     D1. Exact duplicates: identical partner + identical amount + identical
         reference/invoice number. Quantify count and total currency exposure.
     D2. Near duplicates: same partner + same amount posted within a 5-day window
         but different reference. These are the highest-recovery population.
     D3. Transposition duplicates: same partner + same amount where reference numbers
         are digit transpositions of each other (e.g. INV-1243 vs INV-1234).
     D4. Alias duplicates: same amount and date across partner records whose names,
         tax IDs, or bank account numbers are near-identical - indicates duplicate
         vendor master records rather than duplicate invoices.
     D5. Split-transaction test: multiple entries to the same partner on the same day
         that individually fall below an approval threshold but aggregate above it.
     D6. Round-sum test: payments in exact round amounts above the clearly-trivial
         threshold, which are statistically over-represented in fabricated entries.
     D7. Benford first-digit analysis on the payment population (see digit table).
     D8. For every confirmed duplicate, state whether it was subsequently reversed,
         credited, or offset. Only unrecovered items count toward the exposure figure.""",
    ),
    "Tax Compliance": AuditPlan(
        key="Tax Compliance",
        tools="tax_summary, journal_audit, detect_anomalies, calculate_pnl",
        focus="Statutory tax exposure, VAT control account integrity, and filing-to-ledger agreement.",
        pillar_weights={**_DEFAULT_WEIGHTS, "tax_compliance": 45,
                        "ledger_integrity": 20, "transaction_integrity": 15,
                        "subledger_reconciliation": 10, "control_environment": 10},
        procedures="""     T1. VAT control account rollforward:
         opening balance + output VAT - input VAT - payments/refunds = closing balance.
         Any unexplained residual is a reportable exposure - state it in currency.
     T2. Effective rate test: output VAT / taxable revenue, per revenue stream. Compare
         against the statutory rate. Deviations indicate misclassification of zero-rated,
         exempt, or out-of-scope supplies.
     T3. Input VAT recoverability: identify input VAT claimed on categories that are
         commonly blocked (entertainment, staff welfare, passenger vehicles, gifts).
     T4. Reverse-charge / self-assessment: imported services and cross-border purchases
         that should carry a reverse-charge entry on both sides. A missing pair is both
         an understated liability and an understated recoverable.
     T5. Zero-rated vs exempt classification: exempt supplies restrict input recovery,
         zero-rated do not. Misclassification distorts the recoverable ratio.
     T6. Filing-to-ledger agreement: reconcile amounts per filed returns to the GL tax
         accounts for each period in scope. Quantify each variance.
     T7. Withholding tax: identify payments to categories subject to WHT where no
         withholding entry exists.
     T8. Cutoff: tax recognized in the wrong period, particularly credit notes and
         invoices dated near a period boundary.
     T9. Where a liability is identified, estimate the penalty and interest exposure
         separately from the principal, and label it as an estimate.""",
    ),
    "Incomplete Records": AuditPlan(
        key="Incomplete Records",
        tools=("payment_reconciliation, partner_ledger, aging_analysis, "
               "detect_anomalies, receivables_analysis"),
        focus="Completeness assertion — what is missing, not what is wrong.",
        pillar_weights={**_DEFAULT_WEIGHTS, "subledger_reconciliation": 35,
                        "transaction_integrity": 20, "ledger_integrity": 20,
                        "tax_compliance": 10, "control_environment": 15},
        procedures="""     I1. Sequence gap analysis: test document number sequences (invoices, credit notes,
         journal references, payment vouchers) for gaps and duplicates. A gap is either
         a deleted record or an unposted one - both are completeness failures.
     I2. Unapplied cash: customer receipts not matched to an invoice. Age them; anything
         over 60 days indicates a reconciliation process failure, not a timing issue.
     I3. Orphan subledger entries: AR/AP subledger lines with no corresponding GL posting,
         and GL control account movements with no subledger detail.
     I4. Open commitments: purchase orders with no goods receipt, and goods receipts with
         no supplier invoice (the classic unrecorded liability / GRNI exposure).
     I5. Dimension completeness: postings missing partner, cost centre, analytic account,
         or tax code where the account normally requires one.
     I6. Suspense and clearing account aging: balances resting in suspense, clearing, or
         'to be classified' accounts. Age each and quantify.
     I7. Aging and provisioning adequacy: bucket AR into 0-30 / 31-60 / 61-90 / 91-180 /
         180+ days. Compare recorded provision against an expected-credit-loss view. State
         the shortfall in currency if the provision is inadequate.
     I8. Dormant balance test: partner balances with no movement in over 180 days that are
         still carried as current.""",
    ),
    "Journal & Ledger Integrity": AuditPlan(
        key="Journal & Ledger Integrity",
        tools="journal_audit, trial_balance, balance_sheet, detect_anomalies, general_ledger",
        focus="Double-entry integrity and management override of controls (ISA 240).",
        pillar_weights={**_DEFAULT_WEIGHTS, "ledger_integrity": 40,
                        "transaction_integrity": 25, "control_environment": 15,
                        "subledger_reconciliation": 15, "tax_compliance": 5},
        procedures="""     J1. Foot and cross-foot the trial balance: total debits must equal total credits.
         Report the variance in currency, not as a pass/fail adjective.
     J2. Balance sheet equation: Assets = Liabilities + Equity. Any residual is a
         critical finding regardless of size.
     J3. Subledger-to-GL tie-out: AR subledger total to AR control, AP subledger total
         to AP control, inventory subledger to inventory control. Quantify each gap.
     J4. Unbalanced and one-sided journal entries at the individual entry level.
     J5. ISA 240 high-risk journal entry battery (see criteria list). Rank the resulting
         population by amount and report the top exposures.
     J6. Manual vs system-generated ratio by account and by user. A rising manual ratio in
         revenue or cash accounts is a recognized override indicator.
     J7. Post-closing activity: entries posted to a period after it was closed or locked.
     J8. Account pairing analysis: debit/credit account combinations that occur rarely in
         the population, particularly revenue paired with a balance sheet account.
     J9. Retained earnings and equity movements not traceable to a board-approved action.
     J10. Benford first-digit analysis on the journal line population.""",
    ),
    "Bank & Cash Reconciliation": AuditPlan(
        key="Bank & Cash Reconciliation",
        tools=("bank_statement_summary, bank_cash_summary, journal_cards, "
               "payment_reconciliation, detect_anomalies"),
        focus="Cash existence, reconciliation discipline, and misappropriation indicators.",
        pillar_weights={**_DEFAULT_WEIGHTS, "subledger_reconciliation": 35,
                        "transaction_integrity": 25, "control_environment": 20,
                        "ledger_integrity": 15, "tax_compliance": 5},
        procedures="""     B1. Reconciliation rollforward per account: bank statement balance
         +/- deposits in transit +/- outstanding payments +/- unrecorded items
         = general ledger balance. Any residual is a reportable item.
     B2. Outstanding item aging: payments outstanding beyond 90 days are stale and
         likely represent unrecorded voids. Beyond 180 days, treat as a control failure.
     B3. Deposits in transit outstanding more than 3 business days - a classic lapping
         and misappropriation indicator.
     B4. Unrecorded bank activity: charges, interest, FX differences, and returned items
         present on the statement but absent from the ledger.
     B5. Inter-account transfer testing around the period boundary: transfers where the
         debit and credit fall in different periods overstate the combined cash position
         (kiting indicator). Test the final 5 and first 5 days of the window.
     B6. Negative balance test: any cash or bank ledger account showing a credit balance
         at any point during the window.
     B7. Cash-in-hand: ledger balance against the most recent recorded count, and the
         frequency of counts performed.
     B8. Reconciling items unresolved for more than 30 days, and accounts with no
         reconciliation performed at all during the window.
     B9. Round-sum and repeated-amount cash withdrawals above the clearly-trivial
         threshold.""",
    ),
    "Revenue & Margin Integrity": AuditPlan(
        key="Revenue & Margin Integrity",
        tools="discount_leakage, sales_summary, purchase_vs_sales_margin, detect_anomalies",
        focus="Revenue recognition validity, cutoff, and margin leakage quantification.",
        pillar_weights={**_DEFAULT_WEIGHTS, "transaction_integrity": 35,
                        "ledger_integrity": 20, "control_environment": 20,
                        "subledger_reconciliation": 15, "tax_compliance": 10},
        procedures="""     R1. Gross-to-net bridge: gross invoiced value - discounts - credit notes - returns
         - rebates = net recognized revenue. Every deduction quantified in currency and
         as a percentage of gross.
     R2. Discount leakage against policy: transactions discounted above the authorised
         threshold, grouped by approver and by salesperson. Quantify the margin points
         and the currency value surrendered.
     R3. Credit note velocity: credit notes issued shortly after period end against
         invoices raised just before it. This is the primary channel-stuffing indicator.
         Report count, value, and the average gap in days.
     R4. Cutoff testing: revenue recognized in the final 5 days of the period where the
         delivery, shipment, or service date falls in the following period.
     R5. Negative or below-cost margin transactions, with the loss quantified per line.
     R6. Price override analysis: selling prices deviating materially from the price list
         or from the trailing average for the same item and customer tier.
     R7. Revenue without fulfilment: invoices posted with no corresponding delivery or
         service record.
     R8. Round-trip and related-party indicators: a partner appearing on both the sales
         and purchase side with offsetting values in the same window.
     R9. Margin variance decomposition: split the movement in gross margin into price,
         volume, mix, and cost effects so the cause is attributed rather than described.""",
    ),
}

DEFAULT_PRIORITY = "Duplicate Detection"

FALLBACK_PLAN = AuditPlan(
    key="General Integrity Review",
    tools="journal_audit, detect_anomalies, trial_balance, tax_summary, payment_reconciliation",
    focus="Broad integrity sweep across all five pillars.",
    pillar_weights=dict(_DEFAULT_WEIGHTS),
    procedures="""     G1. Trial balance foot and cross-foot; balance sheet equation.
     G2. Subledger-to-GL tie-out for AR, AP and cash.
     G3. ISA 240 high-risk journal entry battery.
     G4. VAT control account rollforward and filing-to-ledger agreement.
     G5. Unapplied cash and stale subledger balance aging.
     G6. Benford first-digit analysis on the transaction population.""",
)


# ==========================================================================
# 3. DATE / SCOPE HELPERS
# ==========================================================================

def _parse_date(value: Any) -> Optional[_date]:
    if value is None or value == "":
        return None
    if isinstance(value, _date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y", "%d/%m/%Y"):
            try:
                return datetime.strptime(value.strip()[:10], fmt).date()
            except ValueError:
                continue
    return None


def _end_of_month(year: int, month: int) -> _date:
    return _date(year, month, calendar.monthrange(year, month)[1])


def _prior_quarter_bounds(today: _date) -> Tuple[_date, _date]:
    """The most recently COMPLETED calendar quarter — what an auditor means by
    'last quarter'. You audit closed periods, not the one still being posted to."""
    current_q = (today.month - 1) // 3 + 1
    if current_q == 1:
        year, pq = today.year - 1, 4
    else:
        year, pq = today.year, current_q - 1
    start_month = 3 * (pq - 1) + 1
    return _date(year, start_month, 1), _end_of_month(year, start_month + 2)


def _fiscal_year_start(today: _date, fy_end_month: int = 12) -> _date:
    """First day of the fiscal year currently in progress."""
    fy_end_month = min(max(int(fy_end_month or 12), 1), 12)
    end_year = today.year if today.month <= fy_end_month else today.year + 1
    previous_fy_end = _end_of_month(end_year - 1, fy_end_month)
    return previous_fy_end + timedelta(days=1)


def _business_days_back(anchor: _date, count: int) -> _date:
    """Anchor minus `count` business days, used for cutoff sub-windows."""
    d, remaining = anchor, count
    while remaining > 0:
        d -= timedelta(days=1)
        if d.weekday() < 5:
            remaining -= 1
    return d


@dataclass
class AuditScope:
    start: _date
    end: _date
    label: str
    explicit: bool
    days: int = 0
    cutoff_start: Optional[_date] = None
    cutoff_end: Optional[_date] = None
    warnings: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.days = (self.end - self.start).days + 1
        self.cutoff_start = _business_days_back(self.end, 5)
        self.cutoff_end = self.end + timedelta(days=7)


def _resolve_scope(
    depth: str,
    today: _date,
    fy_end_month: int,
    explicit_start: Optional[_date],
    explicit_end: Optional[_date],
) -> AuditScope:
    if explicit_start and explicit_end and explicit_end >= explicit_start:
        return AuditScope(
            start=explicit_start,
            end=explicit_end,
            label=f"{explicit_start.isoformat()} to {explicit_end.isoformat()}",
            explicit=True,
        )

    if depth == "Quick Scan (Last 7 days)":
        start = today - timedelta(days=6)
        return AuditScope(
            start=start, end=today, label="Last 7 days", explicit=False,
            warnings=[
                "A 7-day window is too short for trend-based tests. Benford analysis, "
                "aging, and sequence-gap tests require a larger population - state "
                "explicitly which procedures were not performed for lack of data, and "
                "apply the limited-scope score cap."
            ],
        )

    if depth == "Comprehensive (Full Year)":
        start = _fiscal_year_start(today, fy_end_month)
        return AuditScope(
            start=start, end=today, label="Fiscal year to date", explicit=False,
        )

    # Default: Full Depth (Last Quarter)
    start, end = _prior_quarter_bounds(today)
    q = (start.month - 1) // 3 + 1
    return AuditScope(
        start=start, end=end, label=f"Q{q} {start.year} (last completed quarter)",
        explicit=False,
    )


# ==========================================================================
# 4. OUTPUT SCHEMA
# ==========================================================================

OUTPUT_SCHEMA_BLOCK = """```json
{
  "title": "3-6 word audit summary title",
  "score": 88,
  "status": "Attention Needed",
  "grade": "A",
  "currency": "ISO code observed in the source data",

  "alerts": [
    {"text": "Short headline alert", "sub": "Exact count and currency amount, e.g. '3 payments totalling AED 14,250 unapplied to invoices'"}
  ],

  "findings": [
    {
      "title": "Detailed finding title",
      "description": "Root cause, not just the symptom. Cite exact journal reference, account code, partner, date and amount.",
      "severity": "critical | warning | review",
      "deficiency_class": "material_weakness | significant_deficiency | control_deficiency | observation",
      "assertion": "completeness",
      "pillar": "ledger_integrity | subledger_reconciliation | tax_compliance | transaction_integrity | control_environment",
      "procedure_ref": "J5",
      "exposure_value": 0.00,
      "vs_materiality": "above overall | above performance | below performance | clearly trivial",
      "population_tested": "e.g. 1,240 journal lines; 38 flagged",
      "evidence": ["JRNL-2026-00412", "AC-4010", "INV-8821"],
      "recommendation": "Specific, assignable corrective action.",
      "owner": "Function accountable for remediation."
    }
  ],

  "materiality": {
    "benchmark": "pre_tax_income | revenue | total_assets | gross_profit | equity",
    "benchmark_value": 0.00,
    "rate_applied": "5%",
    "overall": 0.00,
    "performance": 0.00,
    "clearly_trivial": 0.00,
    "rationale": "Why this benchmark fits the entity profile."
  },

  "misstatement_summary": {
    "factual": 0.00,
    "judgmental": 0.00,
    "projected": 0.00,
    "total": 0.00,
    "exceeds_overall_materiality": false,
    "conclusion": "Whether aggregate misstatement is material to the financial statements as a whole."
  },

  "pillar_scores": [
    {"pillar": "ledger_integrity", "score": 0, "weight": 25, "summary": "One line."},
    {"pillar": "subledger_reconciliation", "score": 0, "weight": 20, "summary": "One line."},
    {"pillar": "tax_compliance", "score": 0, "weight": 20, "summary": "One line."},
    {"pillar": "transaction_integrity", "score": 0, "weight": 20, "summary": "One line."},
    {"pillar": "control_environment", "score": 0, "weight": 15, "summary": "One line."}
  ],

  "score_calculation": "Show the arithmetic, e.g. '100 base, -30 unbalanced TB (critical), -14 unapplied cash above PM (warning), -4 minor timing = 52; ceiling 58 from critical finding not binding'.",

  "quantified_exposure": {
    "recoverable": 0.00,
    "at_risk": 0.00,
    "unrecorded_liability": 0.00,
    "note": "Recoverable = cash the entity can realistically reclaim. At risk = potential loss if unaddressed."
  },

  "benford_analysis": {
    "performed": false,
    "population_size": 0,
    "mad": 0.000,
    "conformity": "close | acceptable | marginal | nonconformity | not_performed",
    "note": "Which digits deviate and by how much, or why the test could not be run."
  },

  "segregation_of_duties": [
    {"conflict": "Same user created the vendor and approved the payment.", "users_affected": 0, "transactions": 0, "value": 0.00}
  ],

  "data_quality": {
    "tools_returning_data": ["..."],
    "tools_returning_empty": ["..."],
    "procedures_performed": ["J1", "J2"],
    "procedures_not_performed": [{"ref": "J10", "reason": "Population below 300 lines; Benford not statistically valid."}],
    "coverage_note": "What portion of the population was actually examined, and how it was selected.",
    "scope_limitations": "Anything that prevented a conclusion."
  }
}
```"""


# ==========================================================================
# 5. PROMPT CONSTRUCTION
# ==========================================================================

def _build_prompt(
    *,
    today: _date,
    priority: str,
    depth: str,
    plan: AuditPlan,
    scope: AuditScope,
    currency_hint: str,
    materiality_hint: str,
) -> str:
    scope_line = (
        f"Audit Date Range: {scope.start.isoformat()} to {scope.end.isoformat()} "
        f"({scope.days} days). Scope every tool call and every procedure to this window."
    )
    warning_block = (
        "\n".join(f"- {w}" for w in scope.warnings) if scope.warnings else "- None."
    )
    weights_line = ", ".join(f"{k} {v}%" for k, v in plan.pillar_weights.items())

    return f"""<request_context>
Today's Date: {today.isoformat()}
{scope_line}
Scope Label: {scope.label}
Scope Warnings:
{warning_block}

<priority>{priority}</priority>
<audit_focus>{plan.focus}</audit_focus>
<depth>{depth}</depth>
<cutoff_test_window>{scope.cutoff_start.isoformat()} to {scope.cutoff_end.isoformat()}</cutoff_test_window>
<pillar_weights>{weights_line}</pillar_weights>
{currency_hint}
{materiality_hint}
Recommended Tools: {plan.tools}
</request_context>

<role>
You are a Lead Financial Auditor and Certified Forensic Accounting Specialist performing
an integrity inspection that will be read by an audit committee. You work to professional
standards: you establish materiality before you test, you map every finding to the assertion
it affects, you distinguish a control deficiency from a material weakness, and you quantify
exposure in currency rather than describing it in adjectives.

You are also bound by professional scepticism in both directions. You do not soften a real
control failure, and you do not manufacture a finding to appear thorough. An audit that
finds nothing, where nothing is there, is a successful audit.
</role>

<instructions>

1. Tool Execution (Parallel Turn):
   - In your initial turn, call all recommended tools ({plan.tools}) in parallel. Scope every call to the audit date range above. Pass company_ids / tenant_ids from context where required.
   - Once tool results are returned, ALL DATA IS ACQUIRED. DO NOT CALL ANY MORE TOOLS.
   - DO NOT write any scratchpad math, commentary, or conversational text in the response outside the JSON block. Perform calculations directly into the JSON field values.
   - Track which tools returned data and which returned empty. An empty tool is a scope
     limitation that must be disclosed in data_quality, never silently worked around.

2. Double-Entry & Ledger Equivalence and Materiality Framework:
   Establish materiality first before evaluating findings:
{MATERIALITY_POLICY}
   Derive the benchmark value from the retrieved data (calculate_pnl, balance_sheet,
   or sales_summary). If no benchmark can be derived, say so, set materiality to null,
   and treat every finding as unquantified-severity with a capped score.

   Double-Entry & Ledger Equivalence: Verify that Trial Balance debits equal credits (Total Debits == Total Credits) and Balance Sheet holds (Assets == Liabilities + Equity). Inspect journal_audit for any unbalanced journal.

   Materiality then governs everything downstream:
     - Exposure above overall materiality ......... critical candidate
     - Exposure above performance materiality ..... warning candidate
     - Exposure below performance materiality ..... review candidate
     - Exposure below clearly trivial ............. not individually reported
   A finding's severity is driven by BOTH its currency value and its nature. Some findings
   are critical regardless of amount: an out-of-balance trial balance, a breached balance
   sheet equation, evidence of override, or an unrecorded statutory liability.

3. Execute Priority Test Battery:
   Priority: {priority}
{plan.procedures}

   For each procedure, report either a result or an explicit reason it was not performed.
   A procedure silently skipped is a hole in the audit.

4. Cross-Cutting Procedures:

   4a. ISA 240 — MANAGEMENT OVERRIDE (presumed significant risk)
   Journal entry testing is mandatory. Flag entries meeting any of:
{JE_RISK_CRITERIA}
   Report the flagged population size, the value, and the top exposures by amount.
   A flag is an indicator, not a conclusion. Describe what was observed and what control
   it bypasses. Do not assert fraud, intent, or wrongdoing by any named individual.

   4b. BENFORD'S LAW DIGIT ANALYSIS
   Expected first-digit frequencies: {BENFORD_TABLE}
   Requires a population of at least 300 naturally-occurring amounts spanning multiple
   orders of magnitude. Below that, do NOT run it - record it as not performed.
   Report mean absolute deviation (MAD) and interpret:
     MAD < 0.006 close conformity | 0.006-0.012 acceptable |
     0.012-0.015 marginal | > 0.015 nonconformity
   Nonconformity is a prompt to investigate, never a finding on its own.

   4c. SEGREGATION OF DUTIES
   Test for the same user performing conflicting roles: creating a partner and approving
   payment to it; posting a journal and approving it; raising a purchase order and
   receiving against it; issuing a credit note and collecting the related receivable.
   Quantify affected users, transaction count, and value.

   4d. CUTOFF TESTING
   Examine the cutoff window above for transactions recognised in the wrong period -
   revenue, expense accruals, credit notes, and inter-account transfers.

5. Deterministic Integrity Scoring (0-100):
   - Score each of the five pillars 0-100 on its own evidence, then compute the weighted
     overall score using the pillar weights supplied in context.
   - Cross-check that weighted result against a deduction ledger starting from 100:
       Critical findings (-25 to -40 pts each): Unbalanced trial balance, A != L+E, corrupt journal lines, material unrecorded tax exposure.
       Warning findings (-10 to -20 pts each): High-volume unapplied customer payments, material stale receivables, unauthorized discount leakage.
       Review findings (-3 to -5 pts each): Minor timing differences, unclassified minor lines, isolated non-material anomalies.
       Scope limitation (a required tool returned empty) ... -5 each
       Limited scope window (under 30 days) ............... -8
     Deductions scale with materiality: a warning at 3x performance materiality sits at
     the top of its band, one just above the threshold sits at the bottom.
   - Reconcile the two methods. If they differ by more than 8 points, state which you
     adopted and why. Put the full arithmetic in score_calculation.
   - Hard ceilings, applied last and non-negotiable:
       any critical finding .......... score cannot exceed 58
       any material weakness ......... score cannot exceed 52
       any warning finding ........... score cannot exceed 88
   - Then map score to status and grade:
       90-100: status "Verified", grade "AA"
       75-89: status "Attention Needed", grade "A"
       50-74: status "Issues Found", grade "B"
       below 50: status "Critical", grade "C"
     Never report a status that contradicts the findings list.

6. Deficiency Classification:
   Classify every finding using the professional taxonomy:
{DEFICIENCY_CLASSES}
   Map each finding to the assertion at risk, one of: {ASSERTIONS}.

7. Clean Audit & Anti-Hallucination Directives:
   If all tools return balanced, reconciled data with no anomalies above the clearly
   trivial threshold:
     - Set score to 95-100, status to "Verified", grade to "AA".
     - alerts may be an empty array, or a single confirmation entry (e.g. 'All journals, subledgers, and tax lines fully reconciled').
     - findings may be an empty array, or a single record with severity "review"
       documenting what was tested and found clean.
     - Still populate materiality, pillar_scores, and data_quality. A clean opinion
       without disclosed scope is not a clean opinion.
   NEVER fabricate fraud, missing records, fictitious imbalances, or invented journal
   references in order to appear rigorous.

8. Evidence and Fact-Checking:
   - Every finding requires at least one concrete evidence reference: a journal code,
     account code, invoice or payment reference, partner name, or date-plus-amount pair.
     A finding with no traceable reference must not be reported.
   - Never invent an account code, journal number, partner name, or user name.
   - Quantify in the currency present in the source data. Do not convert currencies.
   - Distinguish clearly between what was OBSERVED, DERIVED, and ESTIMATED.
   - Reconcile before emitting: severity is consistent with exposure versus materiality,
     the score respects its ceilings, status and grade match the score band, and every
     alert corresponds to a finding.

9. Strict JSON Format:
   - Output EXACTLY one valid JSON object enclosed within a single ```json ``` block.
   - STRICT REQUIREMENT: Output ZERO text, preamble, or conversational words outside the ```json ``` block.
   - Keep every key even where the value is zero, null, or an empty array.
</instructions>

<output_schema>
{OUTPUT_SCHEMA_BLOCK}
</output_schema>"""


# ==========================================================================
# 6. RESPONSE GUARD
# ==========================================================================

_VALID_SEVERITIES = {"critical", "warning", "review"}
_VALID_DEFICIENCIES = set(DEFICIENCY_SCORE_CEILING)

_REQUIRED_KEYS: Dict[str, Any] = {
    "title": "Integrity Audit",
    "score": 50,
    "status": "Issues Found",
    "grade": "B",
    "currency": "",
    "alerts": list,
    "findings": list,
    "materiality": dict,
    "misstatement_summary": dict,
    "pillar_scores": list,
    "score_calculation": "",
    "quantified_exposure": dict,
    "benford_analysis": dict,
    "segregation_of_duties": list,
    "data_quality": dict,
}


def _derive_status_grade(score: int) -> Tuple[str, str]:
    for low, high, status, grade in SCORE_BANDS:
        if low <= score <= high:
            return status, grade
    return "Critical", "C"


def _normalise_findings(findings: Any) -> List[Dict[str, Any]]:
    if not isinstance(findings, list):
        return []
    cleaned: List[Dict[str, Any]] = []
    for item in findings:
        if not isinstance(item, dict):
            continue
        severity = str(item.get("severity", "review")).strip().lower()
        if severity not in _VALID_SEVERITIES:
            severity = "review"
        deficiency = str(item.get("deficiency_class", "observation")).strip().lower()
        if deficiency not in _VALID_DEFICIENCIES:
            deficiency = "observation"

        evidence = item.get("evidence")
        if isinstance(evidence, str):
            evidence = [evidence]
        elif not isinstance(evidence, list):
            evidence = []

        cleaned.append(
            {
                "title": str(item.get("title") or "Unlabelled finding"),
                "description": str(item.get("description") or ""),
                "severity": severity,
                "deficiency_class": deficiency,
                "assertion": str(item.get("assertion") or ""),
                "pillar": str(item.get("pillar") or ""),
                "procedure_ref": str(item.get("procedure_ref") or ""),
                "exposure_value": float(item.get("exposure_value") or 0.0),
                "vs_materiality": str(item.get("vs_materiality") or ""),
                "population_tested": str(item.get("population_tested") or ""),
                "evidence": [str(e) for e in evidence],
                "recommendation": str(item.get("recommendation") or ""),
                "owner": str(item.get("owner") or ""),
            }
        )
    return cleaned


def _apply_score_ceilings(score: int, findings: List[Dict[str, Any]]) -> Tuple[int, List[str]]:
    """A critical finding cannot coexist with a 'Verified' status. Enforce it here
    rather than trusting the model to police itself."""
    ceiling, reasons = 100, []
    for f in findings:
        sev_cap = SEVERITY_SCORE_CEILING.get(f["severity"], 100)
        def_cap = DEFICIENCY_SCORE_CEILING.get(f["deficiency_class"], 100)
        if sev_cap < ceiling:
            ceiling = sev_cap
            reasons.append(f"severity '{f['severity']}' caps score at {sev_cap}")
        if def_cap < ceiling:
            ceiling = def_cap
            reasons.append(f"deficiency class '{f['deficiency_class']}' caps score at {def_cap}")
    if score > ceiling:
        return ceiling, reasons
    return score, []


def _guard_payload(
    payload: Any,
    *,
    plan: AuditPlan,
    scope: AuditScope,
) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        payload = {}

    out: Dict[str, Any] = dict(payload)

    for key, default in _REQUIRED_KEYS.items():
        if key not in out or out[key] is None:
            out[key] = default() if callable(default) else default
        elif callable(default) and not isinstance(out[key], default):
            out[key] = default()

    out["findings"] = _normalise_findings(out.get("findings"))

    try:
        score = int(round(float(out.get("score", 50))))
    except (TypeError, ValueError):
        score = 50
    score = max(0, min(100, score))

    score, ceiling_reasons = _apply_score_ceilings(score, out["findings"])
    out["score"] = score

    status, grade = _derive_status_grade(score)
    out["status"], out["grade"] = status, grade

    if ceiling_reasons:
        note = "Server-applied score ceiling: " + "; ".join(dict.fromkeys(ceiling_reasons))
        out["score_calculation"] = f"{out.get('score_calculation', '')} | {note}".strip(" |")

    alerts = out["alerts"] if isinstance(out["alerts"], list) else []
    out["alerts"] = [
        {"text": str(a.get("text", "")), "sub": str(a.get("sub", ""))}
        for a in alerts
        if isinstance(a, dict) and a.get("text")
    ][:8]

    dq = out["data_quality"]
    dq.setdefault("tools_returning_data", [])
    dq.setdefault("tools_returning_empty", [])
    dq.setdefault("procedures_performed", [])
    dq.setdefault("procedures_not_performed", [])
    dq.setdefault("coverage_note", "")
    dq.setdefault("scope_limitations", "; ".join(scope.warnings))

    out["benford_analysis"].setdefault("performed", False)
    out["benford_analysis"].setdefault("conformity", "not_performed")

    out["priority"] = plan.key
    out["audit_focus"] = plan.focus
    return out


# ==========================================================================
# 7. RUNNER FUNCTION
# ==========================================================================

async def execute_forensic_audit(
    *,
    req: Any,
    primary_tenant_id: Optional[str],
    resolved_tenant_ids: Optional[List[str]],
    resolved_company_ids: Optional[List[int]],
    run_node_fn: Callable[..., Any],
) -> Dict[str, Any]:
    """Coordinates audit prompt construction, LLM execution, and payload guarding."""
    priority = (getattr(req, "priority", None) or "").strip() or DEFAULT_PRIORITY
    depth = (getattr(req, "depth", None) or "").strip() or "Full Depth (Last Quarter)"
    plan = AUDIT_PLANS.get(priority, FALLBACK_PLAN)

    session_id = getattr(req, "session_id", None) or str(uuid.uuid4())
    today = _date.today()

    fy_end_month = getattr(req, "fiscal_year_end_month", 12) or 12
    currency = (getattr(req, "currency", None) or "").strip()
    materiality_override = getattr(req, "materiality_override", None)

    scope = _resolve_scope(
        depth,
        today,
        fy_end_month,
        _parse_date(getattr(req, "start_date", None)),
        _parse_date(getattr(req, "end_date", None)),
    )
    if scope.days < 30:
        scope.warnings.append(
            "Audit window is under 30 days. Apply the limited-scope deduction and list "
            "every procedure that could not be performed on this population size."
        )

    currency_hint = (
        f"<reporting_currency>{currency}</reporting_currency>"
        if currency
        else "<reporting_currency>Detect from the tool data and state it explicitly. "
             "Do not mix or convert currencies.</reporting_currency>"
    )

    if materiality_override:
        pm = round(float(materiality_override) * PERFORMANCE_MATERIALITY_RATE, 2)
        ct = round(float(materiality_override) * CLEARLY_TRIVIAL_RATE, 2)
        materiality_hint = (
            f"<materiality_override>Overall materiality is fixed at "
            f"{materiality_override} by the engagement. Performance materiality "
            f"{pm}, clearly trivial threshold {ct}. Do not re-derive these - use them "
            f"as given and record the source as 'engagement-specified'.</materiality_override>"
        )
    else:
        materiality_hint = (
            "<materiality_override>None supplied. Derive overall materiality from the "
            "retrieved financials using the benchmark policy in the instructions, and "
            "justify the benchmark chosen.</materiality_override>"
        )

    prompt = _build_prompt(
        today=today,
        priority=priority,
        depth=depth,
        plan=plan,
        scope=scope,
        currency_hint=currency_hint,
        materiality_hint=materiality_hint,
    )

    user_label = f"Audit: {priority} — {depth}"
    session_tenant_id = primary_tenant_id or "default"

    try:
        structured = await run_node_fn(
            prompt=prompt,
            user_label=user_label,
            msg_type="audit",
            session_id=session_id,
            session_tenant_id=session_tenant_id,
            resolved_tenant_ids=resolved_tenant_ids,
            resolved_company_ids=resolved_company_ids,
        )
        guarded = _guard_payload(structured, plan=plan, scope=scope)
        return {
            **guarded,
            "session_id": session_id,
            "depth": depth,
            "scope": {
                "start": scope.start.isoformat(),
                "end": scope.end.isoformat(),
                "days": scope.days,
                "label": scope.label,
                "explicit_range": scope.explicit,
                "cutoff_window": {
                    "start": scope.cutoff_start.isoformat(),
                    "end": scope.cutoff_end.isoformat(),
                },
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        log_error("run_audit", e)
        raise HTTPException(
            status_code=500,
            detail="Failed to run integrity audit. Please try again.",
        )
