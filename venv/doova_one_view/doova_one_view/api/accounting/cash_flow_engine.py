# doova_one_view/api/accounting/cash_flow_engine.py

"""
Odoo Enterprise-Grade Dual-Mode Cash Flow Statement Engine.
Supports:
1. Live Odoo Enterprise Engine (`account.report.get_report_information`) via JSON-RPC.
2. High-Precision Local IAS 7 Reconciler (operating/investing/financing/unclassified breakdown,
   liquidity clearing elimination, advance reconciler, tag overrides, multi-currency).
3. Transaction-level drill-down metric queries with synchronized date filters.
"""

from typing import Dict, Any, List, Optional
import logging
import time
import requests
import urllib3
from django.db.models import Sum, Q

from odoo_app.models.tenant import Tenant
from odoo_app.models.account_move import AccountMove
from odoo_app.models.account_move_line import AccountMoveLine
from odoo_app.models.account_journal import AccountJournal
from odoo_app.models.account_partial_reconcile import AccountPartialReconcile
from odoo_app.models.chart_of_accounts import ChartOfAccounts
from odoo_app.models.account_account_tag import AccountAccountTag
from doova_one_view.api.common.utils import decrypt_api_key
from doova_one_view.api.kpi.service import _get_rate_map, _get_conversion_rate, _to_float

logger = logging.getLogger(__name__)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class CashFlowEngine:
    """
    Production-grade Dual-Mode Cash Flow Statement Engine matching Odoo Enterprise account_reports.
    """

    @classmethod
    def get_liquidity_filter(cls, tenant_ids: Optional[list[str]] = None) -> Q:
        """
        Builds the canonical liquidity Q-filter identifying all bank, cash, and
        clearing accounts (IAS 7 Cash & Cash Equivalents).
        """
        from doova_one_view.api.agent.query_context import normalize_tenant_ids
        clean_tenants = normalize_tenant_ids(tenant_ids)
        journal_qs = AccountJournal.objects.filter(type__in=['bank', 'cash']).exclude(default_account_code__isnull=True)
        if clean_tenants:
            if len(clean_tenants) == 1:
                journal_qs = journal_qs.filter(tenant_id=clean_tenants[0])
            else:
                journal_qs = journal_qs.filter(tenant_id__in=clean_tenants)
        journal_account_codes = list(journal_qs.values_list('default_account_code', flat=True))

        # Only use numeric account codes from journals (e.g. "51200001", "53000001").
        # Short journal codes like "Bank", "Cash", "Cheques" must be excluded because
        # they match unrelated accounts (e.g. "Bank Loans Bange", "Bank Charges").
        numeric_codes = [
            c for c in journal_account_codes
            if c and c.isdigit() and len(c) >= 6
        ]
        base_codes_all = ["51100098", "51200098"] + numeric_codes

        return (
            Q(account_type="asset_cash") |
            Q(account_type="asset_current", account_name__icontains="outstanding") |
            Q(account_type="asset_current", account_name__icontains="cheque") |
            Q(account_type="asset_current", account_name__icontains="coupon") |
            Q(account_type__in=["asset_cash", "asset_current"], account_code__in=base_codes_all)
        )

    @classmethod
    def _fetch_live_odoo_single_tenant(
        cls,
        tenant: Tenant,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        company_ids: Optional[List[int]] = None,
        base_currency: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Fetches official pre-calculated Cash Flow Statement from a single tenant's Odoo Enterprise
        via JSON-RPC account.report.get_report_information respecting:
        - Multi-Company: allowed_company_ids context & options.companies
        - Time Period: date_from / date_to
        - Currency: target base_currency conversion
        """
        url = (tenant.odoo_url or "").rstrip('/')
        db = tenant.odoo_database
        login = tenant.odoo_username or "ali.chamas@odoo.com"
        api_key = decrypt_api_key(tenant.api_key_encrypted) if tenant.api_key_encrypted else ""

        if not url or not db or not api_key:
            logger.warning(f"Tenant {tenant.id} missing credentials for live Odoo fetch.")
            return None

        session = requests.Session()
        session.verify = False

        # 1. Authenticate
        try:
            auth_payload = {
                "jsonrpc": "2.0",
                "method": "call",
                "params": {"service": "common", "method": "authenticate", "args": [db, login, api_key, {}]},
                "id": 1
            }
            auth_res = session.post(f"{url}/jsonrpc", json=auth_payload, timeout=12).json()
            uid = auth_res.get("result")
            if not uid:
                logger.warning(f"Live Odoo authentication failed for tenant {tenant.id}: {auth_res}")
                return None
        except Exception as e:
            logger.warning(f"Live Odoo connection failed for tenant {tenant.id}: {e}")
            return None

        # Build RPC Context for Multi-Company
        rpc_context = {}
        if company_ids:
            rpc_context["allowed_company_ids"] = company_ids
            rpc_context["company_ids"] = company_ids
            rpc_context["company_id"] = company_ids[0]

        # Helper for execute_kw
        req_id = 2
        def rpc_call(model, method, args, kwargs=None):
            nonlocal req_id
            req_id += 1
            call_kwargs = kwargs or {}
            if rpc_context and "context" not in call_kwargs:
                call_kwargs["context"] = rpc_context
            elif rpc_context and "context" in call_kwargs:
                call_kwargs["context"].update(rpc_context)

            payload = {
                "jsonrpc": "2.0",
                "method": "call",
                "params": {
                    "service": "object",
                    "method": "execute_kw",
                    "args": [db, uid, api_key, model, method, args, call_kwargs]
                },
                "id": req_id
            }
            r = session.post(f"{url}/jsonrpc", json=payload, timeout=25).json()
            if "error" in r:
                logger.error(f"Odoo RPC error {model}.{method}: {r['error']}")
                return None
            return r.get("result")

        try:
            # 2. Locate Cash Flow Report ID
            reports = rpc_call("account.report", "search_read", [[["name", "ilike", "Cash Flow"]]], {"fields": ["id", "name"]})
            if not reports:
                logger.info(f"No Cash Flow report found in account.report on remote Odoo for tenant {tenant.id}.")
                return None
            
            report_id = reports[0]["id"]

            # 3. Build options respecting Multi-Company and Time Period
            prev_options = {
                "unfold_all": True
            }
            if company_ids:
                prev_options["companies"] = [{"id": cid} for cid in company_ids]

            if start_date or end_date:
                prev_options["date"] = {
                    "date_from": start_date or "2020-01-01",
                    "date_to": end_date or "2099-12-31",
                    "filter": "custom",
                    "mode": "range"
                }

            options = rpc_call("account.report", "get_options", [report_id], {"previous_options": prev_options})
            if not options:
                return None

            # 4. Fetch computed report information
            report_data = rpc_call("account.report", "get_report_information", [report_id, options])
            if not report_data or "lines" not in report_data:
                return None

            # 5. Determine source company currency
            source_currency = "XAF"
            try:
                co_data = rpc_call("res.company", "search_read", [[["id", "in", company_ids or [1]]]], {"fields": ["currency_id"]})
                if co_data and co_data[0].get("currency_id"):
                    source_currency = co_data[0]["currency_id"][1]
            except Exception:
                pass

            return cls._normalize_odoo_lines(
                lines=report_data.get("lines", []),
                tenant_id=str(tenant.id),
                source_currency=source_currency,
                base_currency=base_currency
            )

        except Exception as e:
            logger.error(f"Error fetching live Odoo Cash Flow for tenant {tenant.id}: {e}")
            return None

    @classmethod
    def fetch_live_odoo_cash_flow(
        cls,
        tenant: Optional[Tenant] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        company_ids: Optional[List[int]] = None,
        base_currency: Optional[str] = None,
        tenant_ids: Optional[List[str]] = None,
        tenants: Optional[List[Tenant]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Fetches official pre-calculated Cash Flow Statement from one or multiple Odoo Enterprise instances.
        Supports single tenant and multi-tenant consolidation with target base_currency conversion.
        """
        resolved_tenants: List[Tenant] = []
        if tenants:
            resolved_tenants = list(tenants)
        elif tenant_ids:
            resolved_tenants = list(Tenant.objects.filter(id__in=tenant_ids))
        elif tenant:
            resolved_tenants = [tenant]

        if not resolved_tenants:
            return None

        if len(resolved_tenants) == 1:
            return cls._fetch_live_odoo_single_tenant(
                tenant=resolved_tenants[0],
                start_date=start_date,
                end_date=end_date,
                company_ids=company_ids,
                base_currency=base_currency,
            )

        # Multi-Tenant Consolidation across live Odoo instances
        consolidated = {
            "beginning_balance": 0.0,
            "operating_activities": {
                "customer_advances": 0.0,
                "customer_payments": 0.0,
                "supplier_advances": 0.0,
                "supplier_payments": 0.0,
                "cash_received_from_operating_activities": 0.0,
                "cash_paid_for_operating_activities": 0.0,
                "direct_receipts": 0.0,
                "direct_payments": 0.0,
                "total": 0.0,
            },
            "investing_activities": {"cash_in": 0.0, "cash_out": 0.0, "total": 0.0},
            "financing_activities": {"cash_in": 0.0, "cash_out": 0.0, "total": 0.0},
            "unclassified_activities": {"cash_in": 0.0, "cash_out": 0.0, "total": 0.0},
            "net_increase": 0.0,
            "net_change_in_cash": 0.0,
            "closing_balance": 0.0,
            "details": [],
            "raw_hierarchy": [],
            "is_validated_fixture": False,
            "source_engine": "odoo_enterprise_live_multi_tenant",
        }

        successful_tenants = 0
        for t in resolved_tenants:
            res = cls._fetch_live_odoo_single_tenant(
                tenant=t,
                start_date=start_date,
                end_date=end_date,
                company_ids=company_ids,
                base_currency=base_currency,
            )
            if not res:
                # Fallback to local computation for this tenant if live connection unavailable
                try:
                    res = cls.compute_local_cash_flow(
                        tenant_id=str(t.id),
                        start_date=start_date,
                        end_date=end_date,
                        company_ids=company_ids,
                        base_currency=base_currency,
                    )
                except Exception:
                    continue

            successful_tenants += 1
            consolidated["beginning_balance"] += res.get("beginning_balance", 0.0)
            consolidated["closing_balance"] += res.get("closing_balance", 0.0)
            consolidated["net_increase"] += res.get("net_increase", 0.0)
            consolidated["net_change_in_cash"] += res.get("net_change_in_cash", 0.0)

            for sec in ("operating_activities", "investing_activities", "financing_activities", "unclassified_activities"):
                sec_dict = res.get(sec, {})
                for k, v in sec_dict.items():
                    if isinstance(v, (int, float)):
                        consolidated[sec][k] = consolidated[sec].get(k, 0.0) + v

            for item in res.get("details", []):
                item_copy = dict(item)
                item_copy["tenant_id"] = str(t.id)
                item_copy["tenant_name"] = t.name
                consolidated["details"].append(item_copy)

            for item in res.get("raw_hierarchy", []):
                item_copy = dict(item)
                item_copy["tenant_id"] = str(t.id)
                consolidated["raw_hierarchy"].append(item_copy)

        if successful_tenants == 0:
            return None

        return consolidated

    @classmethod
    def _normalize_odoo_lines(
        cls,
        lines: List[Dict[str, Any]],
        tenant_id: str,
        source_currency: str = "XAF",
        base_currency: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Normalizes Odoo's nested report line list into the canonical Doova One View schema,
        converting amounts to base_currency if required.
        """
        effective_base = base_currency or "XAF"
        rate_map = _get_rate_map()
        conv_rate = _get_conversion_rate(source_currency, effective_base, rate_map)

        def parse_col_val(line):
            cols = line.get("columns", [])
            if cols and isinstance(cols[0], dict):
                raw = str(cols[0].get("name", "0")).replace(",", "").strip()
                try:
                    return float(raw) * conv_rate
                except ValueError:
                    return 0.0
            return 0.0

        beginning_bal = 0.0
        closing_bal = 0.0
        net_inc = 0.0
        cust_adv = 0.0
        supp_adv = 0.0
        direct_rec = 0.0
        direct_paid = 0.0
        op_total = 0.0
        inv_in = 0.0
        inv_out = 0.0
        inv_total = 0.0
        fin_in = 0.0
        fin_out = 0.0
        fin_total = 0.0
        unclass_in = 0.0
        unclass_out = 0.0
        unclass_total = 0.0

        raw_hierarchy = []

        for l in lines:
            name = l.get("name", "").strip()
            name_lower = name.lower()
            val = parse_col_val(l)
            level = l.get("level", 0)
            lid = l.get("id", "")

            raw_hierarchy.append({
                "name": name,
                "level": level,
                "amount": val,
                "line_id": lid,
            })

            parts = lid.split('|')
            section_key = parts[1].rstrip('~') if len(parts) >= 2 else ''
            is_summary_line = '|~account.account~' not in lid

            if is_summary_line:
                if section_key == 'opening_balance' or 'beginning balance' in name_lower or 'opening balance' in name_lower:
                    beginning_bal = val
                elif section_key == 'closing_balance' or 'closing balance' in name_lower or 'ending balance' in name_lower:
                    closing_bal = val
                elif section_key == 'net_increase' or 'net increase' in name_lower or 'net change' in name_lower:
                    net_inc = val
                elif section_key == 'operating_activities' or ('operating activities' in name_lower and level in (1, 2)):
                    op_total = val
                elif section_key == 'advance_payments_customer' or ('customer' in name_lower and 'advance' in name_lower):
                    cust_adv = val
                elif section_key == 'advance_payments_suppliers' or ('supplier' in name_lower and 'advance' in name_lower):
                    supp_adv = val
                elif section_key == 'received_operating_activities':
                    direct_rec = val
                elif section_key == 'paid_operating_activities':
                    direct_paid = val
                elif section_key == 'investing_activities' or ('investing' in name_lower and level in (1, 2)):
                    inv_total = val
                elif section_key == 'investing_activities_cash_in':
                    inv_in = val
                elif section_key == 'investing_activities_cash_out':
                    inv_out = val
                elif section_key == 'financing_activities' or ('financing' in name_lower and level in (1, 2)):
                    fin_total = val
                elif section_key == 'financing_activities_cash_in':
                    fin_in = val
                elif section_key == 'financing_activities_cash_out':
                    fin_out = val
                elif section_key == 'unclassified_activities' or ('unclassified activities' in name_lower and level in (1, 2)):
                    unclass_total = val
                elif section_key == 'unclassified_activities_cash_in':
                    unclass_in = val
                elif section_key == 'unclassified_activities_cash_out':
                    unclass_out = val

        if op_total == 0.0 and (cust_adv != 0.0 or supp_adv != 0.0 or direct_rec != 0.0 or direct_paid != 0.0):
            op_total = cust_adv + supp_adv + direct_rec + direct_paid

        if unclass_total == 0.0 and (unclass_in != 0.0 or unclass_out != 0.0):
            unclass_total = unclass_in - abs(unclass_out)

        if inv_total == 0.0 and (inv_in != 0.0 or inv_out != 0.0):
            inv_total = inv_in - abs(inv_out)

        if fin_total == 0.0 and (fin_in != 0.0 or fin_out != 0.0):
            fin_total = fin_in - abs(fin_out)

        if net_inc == 0.0 and closing_bal != 0.0:
            net_inc = closing_bal - beginning_bal

        return {
            "beginning_balance": beginning_bal,
            "operating_activities": {
                "customer_payments": cust_adv,
                "customer_advances": cust_adv,
                "supplier_payments": supp_adv,
                "supplier_advances": supp_adv,
                "cash_received_from_operating_activities": direct_rec,
                "cash_paid_for_operating_activities": direct_paid,
                "direct_receipts": direct_rec,
                "direct_payments": direct_paid,
                "total": op_total,
            },
            "investing_activities": {
                "cash_in": inv_in if inv_in != 0.0 else max(0.0, inv_total),
                "cash_out": -abs(inv_out) if inv_out != 0.0 else (-abs(inv_total) if inv_total < 0 else 0.0),
                "total": inv_total,
            },
            "financing_activities": {
                "cash_in": fin_in if fin_in != 0.0 else max(0.0, fin_total),
                "cash_out": -abs(fin_out) if fin_out != 0.0 else (-abs(fin_total) if fin_total < 0 else 0.0),
                "total": fin_total,
            },
            "unclassified_activities": {
                "cash_in": unclass_in,
                "cash_out": -abs(unclass_out) if unclass_out > 0 else unclass_out,
                "total": unclass_total,
            },
            "net_increase": net_inc,
            "net_change_in_cash": net_inc,
            "closing_balance": closing_bal,
            "details": raw_hierarchy,
            "raw_hierarchy": raw_hierarchy,
            "is_validated_fixture": False,
            "source_engine": "odoo_enterprise_live",
        }

    @classmethod
    def compute_local_cash_flow(
        cls,
        tenant_id: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        company_ids: Optional[List[int]] = None,
        base_currency: Optional[str] = None,
        tenant_ids: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Executes the exact Odoo Direct-Method Reconciliation-Aware Cash Flow Calculation Engine on local Postgres tables.

        Algorithm (Faithful implementation of Odoo Enterprise account.cash.flow.report.handler):
        1. Liquidity Universe: Bank & Cash journal default accounts + transit clearing accounts resolved canonically.
        2. Opening Cash: SUM(debit - credit) on liquidity accounts strictly before start_date.
        3. Payment Moves: Discovers all posted journal moves in reporting period touching liquidity.
        4. Pure Debit/Credit-Driven Counterpart & Reconciliation Processing:
           - Direct non-AR/AP lines (Bank Charges, Payroll, Taxes, Loans, Capex) are dispatched immediately
             using native signed accounting balance (debit - credit).
           - AR/AP lines (asset_receivable, liability_payable) start with raw signed balance (debit - credit).
           - Reconciliation traversal ONLY FROM AR/AP lines:
             * If payment AML is credit side: residual balance += partial.amount, signed_rec = +partial.amount.
             * If payment AML is debit side: residual balance -= partial.amount, signed_rec = -partial.amount.
           - Unreconciled residuals map to Customer Advances / Supplier Advances (-balance).
           - Reconciled commercial moves (excluding other liquidity moves) allocate each non-matched line proportionally:
             Allocated Balance = Line Balance * (Signed Reconciled Total / Original Matched AR/AP Total).
           - Zero-balance AR/AP edge case on invoices handled by direct matched account dispatch.
        5. Closing Cash: SUM(debit - credit) on liquidity accounts through end_date.
        6. Validation: Computes Unexplained Difference = (Closing - Opening) - Net Increase.
        """
        from decimal import Decimal
        from collections import defaultdict
        from odoo_app.models.account_account_tag import AccountAccountTag
        from odoo_app.models.chart_of_accounts import ChartOfAccounts
        from odoo_app.models.account_partial_reconcile import AccountPartialReconcile
        from odoo_app.models.account_journal import AccountJournal

        effective_base = base_currency or "XAF"
        rate_map = _get_rate_map()

        # ── Step 1: Canonical Liquidity Universe ────────────────────────────────────
        journal_account_codes = list(
            AccountJournal.objects.filter(
                tenant_id=tenant_id,
                type__in=['bank', 'cash']
            ).exclude(
                default_account_code__isnull=True
            ).values_list('default_account_code', flat=True)
        )
        numeric_codes = [c for c in journal_account_codes if c and c.isdigit() and len(c) >= 6]
        base_codes = set(["51100098", "51200098"] + numeric_codes)

        liq_filter = (
            Q(account_type="asset_cash") |
            Q(account_type="asset_current", account_name__icontains="outstanding") |
            Q(account_type="asset_current", account_name__icontains="cheque") |
            Q(account_type="asset_current", account_name__icontains="coupon") |
            Q(account_type__in=["asset_cash", "asset_current"], account_code__in=list(base_codes))
        )

        def is_liquidity_line(l: Dict[str, Any]) -> bool:
            atype = l.get('account_type') or ''
            aname = (l.get('account_name') or '').lower()
            acode = str(l.get('account_code') or '')
            return (
                atype == 'asset_cash'
                or 'outstanding' in aname
                or 'cheque' in aname
                or 'coupon' in aname
                or acode in base_codes
            )

        # ── Step 2: Exact Odoo Tag Mapping (tag_id -> 'operating' | 'investing' | 'financing') ──
        tag_section_map: Dict[int, str] = {}
        for tag in AccountAccountTag.objects.filter(tenant_id=tenant_id, applicability='accounts'):
            n = (tag.name or '').lower()
            if 'operating' in n:
                tag_section_map[tag.odoo_id] = 'operating'
            elif 'invest' in n:
                tag_section_map[tag.odoo_id] = 'investing'
            elif 'financ' in n:
                tag_section_map[tag.odoo_id] = 'financing'

        # (company_id, account_code, account_name) -> section
        acc_section: Dict[tuple, str] = {}
        for acc in ChartOfAccounts.objects.filter(tenant_id=tenant_id).exclude(tag_ids=[]):
            key = (acc.company_id, str(acc.code or ''), acc.name)
            for tag_id in (acc.tag_ids or []):
                if tag_id in tag_section_map:
                    acc_section[key] = tag_section_map[tag_id]
                    break

        # ── Step 3: Base QuerySets & Opening Balance ─────────────────────────────────
        base_qs = AccountMove.objects.filter(tenant_id=tenant_id, state='posted')
        if tenant_ids:
            base_qs = base_qs.filter(tenant_id__in=tenant_ids)
        if company_ids:
            base_qs = base_qs.filter(company_id__in=company_ids)

        open_qs = base_qs.filter(date__lt=start_date) if start_date else base_qs.none()
        open_lines = AccountMoveLine.objects.filter(
            account_move__in=open_qs
        ).filter(liq_filter).values('company__currency_code').annotate(
            net=Sum('debit') - Sum('credit')
        )
        beginning_balance = 0.0
        for ol in open_lines:
            curr = ol.get('company__currency_code') or effective_base
            rate = _get_conversion_rate(curr, effective_base, rate_map)
            beginning_balance += _to_float(ol['net']) * rate

        # ── Step 4: Period Moves Touching Liquidity ──────────────────────────────────
        period_qs = base_qs
        if start_date:
            period_qs = period_qs.filter(date__gte=start_date)
        if end_date:
            period_qs = period_qs.filter(date__lte=end_date)

        liq_move_ids = set(
            AccountMoveLine.objects.filter(
                account_move__in=period_qs
            ).filter(liq_filter).values_list('account_move_id', flat=True).distinct()
        )

        # ── Step 5: Closing Liquidity Balance (<= end_date) ──────────────────────────
        close_qs = base_qs.filter(date__lte=end_date) if end_date else base_qs
        close_lines = AccountMoveLine.objects.filter(
            account_move__in=close_qs
        ).filter(liq_filter).values('company__currency_code').annotate(
            net=Sum('debit') - Sum('credit')
        )
        closing_balance = 0.0
        for cl in close_lines:
            curr = cl.get('company__currency_code') or effective_base
            rate = _get_conversion_rate(curr, effective_base, rate_map)
            closing_balance += _to_float(cl['net']) * rate

        actual_net_change = closing_balance - beginning_balance

        if not liq_move_ids:
            return {
                'beginning_balance': beginning_balance,
                'operating_activities': {
                    'customer_payments': 0.0,
                    'customer_advances': 0.0,
                    'supplier_payments': 0.0,
                    'supplier_advances': 0.0,
                    'cash_received_from_operating_activities': 0.0,
                    'cash_paid_for_operating_activities': 0.0,
                    'direct_receipts': 0.0,
                    'direct_payments': 0.0,
                    'total': 0.0,
                },
                'investing_activities': {'cash_in': 0.0, 'cash_out': 0.0, 'total': 0.0},
                'financing_activities': {'cash_in': 0.0, 'cash_out': 0.0, 'total': 0.0},
                'unclassified_activities': {'cash_in': 0.0, 'cash_out': 0.0, 'total': 0.0},
                'net_increase': 0.0,
                'net_change_in_cash': 0.0,
                'actual_net_change_in_cash': actual_net_change,
                'unexplained_difference': actual_net_change,
                'closing_balance': closing_balance,
                'is_validated_fixture': False,
                'source_engine': 'local_ias7_reconciler',
            }

        # ── Step 6: Classification Engine (Pure Debit/Credit Driven) ─────────────────
        CF = {
            "operating": {
                "customer_advances": 0.0,
                "cash_in": 0.0,
                "supplier_advances": 0.0,
                "cash_out": 0.0,
            },
            "investing": {
                "cash_in": 0.0,
                "cash_out": 0.0,
            },
            "financing": {
                "cash_in": 0.0,
                "cash_out": 0.0,
            },
            "unclassified": {
                "cash_in": 0.0,
                "cash_out": 0.0,
            },
        }

        def dispatch(company_id: Any, account_code: Any, account_name: Any, atype: str, signed_amount: float, currency_code: str):
            rate = _get_conversion_rate(currency_code or effective_base, effective_base, rate_map)
            amt = signed_amount * rate
            if abs(amt) < 0.0001:
                return

            if atype == 'asset_receivable':
                CF["operating"]["customer_advances"] += -amt
                return
            if atype == 'liability_payable':
                CF["operating"]["supplier_advances"] += -amt
                return

            key = (company_id, str(account_code or ''), account_name)
            cat = acc_section.get(key, "unclassified")
            if amt < 0:
                CF[cat]["cash_in"] += -amt
            else:
                CF[cat]["cash_out"] += -amt

        # Fetch lines for payment moves
        payment_lines = list(AccountMoveLine.objects.filter(
            account_move_id__in=liq_move_ids
        ).values(
            'id', 'odoo_id', 'account_move_id', 'company_id', 'account_code', 'account_name',
            'account_type', 'debit', 'credit', 'company__currency_code'
        ))

        ar_ap_payment_lines = {}
        for l in payment_lines:
            if is_liquidity_line(l):
                continue

            balance = _to_float(l['debit']) - _to_float(l['credit'])
            atype = l['account_type'] or ''

            if atype not in ('asset_receivable', 'liability_payable'):
                dispatch(l['company_id'], l['account_code'], l['account_name'], atype, balance, l.get('company__currency_code'))
            else:
                ar_ap_payment_lines[l['id']] = {
                    'company_id': l['company_id'],
                    'account_code': l['account_code'],
                    'account_name': l['account_name'],
                    'account_type': atype,
                    'balance': balance,
                    'currency': l.get('company__currency_code'),
                }

        # ── Reconciliation traversal ONLY FROM AR/AP lines ───────────────────────────
        ar_ap_ids = set(ar_ap_payment_lines.keys())
        rec_qs = AccountPartialReconcile.objects.filter(
            Q(debit_move_line_id__in=ar_ap_ids) | Q(credit_move_line_id__in=ar_ap_ids)
        )
        if start_date:
            rec_qs = rec_qs.filter(max_date__gte=start_date)
        if end_date:
            rec_qs = rec_qs.filter(max_date__lte=end_date)

        partials = list(rec_qs.values('id', 'debit_move_line_id', 'credit_move_line_id', 'amount'))

        external_line_ids = set()
        for p in partials:
            deb_id = p['debit_move_line_id']
            cred_id = p['credit_move_line_id']
            if deb_id in ar_ap_ids and cred_id not in ar_ap_ids:
                external_line_ids.add(cred_id)
            elif cred_id in ar_ap_ids and deb_id not in ar_ap_ids:
                external_line_ids.add(deb_id)

        ext_line_map = {
            l['id']: l for l in AccountMoveLine.objects.filter(id__in=external_line_ids).values(
                'id', 'account_move_id', 'company_id', 'account_code', 'account_name', 'account_type', 'company__currency_code'
            )
        }

        reconciled_by_move_acc = defaultdict(lambda: defaultdict(float))
        reconciled_totals_by_move = defaultdict(float)
        ext_move_currencies = {}
        ext_move_companies = {}

        for p in partials:
            amt = _to_float(p['amount'])
            deb_id = p['debit_move_line_id']
            cred_id = p['credit_move_line_id']

            if cred_id in ar_ap_payment_lines:
                ar_ap_payment_lines[cred_id]['balance'] += amt
                signed_rec = +amt
                if deb_id in ext_line_map:
                    ext_line = ext_line_map[deb_id]
                    mid = ext_line['account_move_id']
                    if mid not in liq_move_ids:
                        acc_key = (ext_line['account_code'], ext_line['account_name'])
                        reconciled_by_move_acc[mid][acc_key] += signed_rec
                        reconciled_totals_by_move[mid] += signed_rec
                        ext_move_currencies[mid] = ext_line.get('company__currency_code')
                        ext_move_companies[mid] = ext_line.get('company_id')

            elif deb_id in ar_ap_payment_lines:
                ar_ap_payment_lines[deb_id]['balance'] -= amt
                signed_rec = -amt
                if cred_id in ext_line_map:
                    ext_line = ext_line_map[cred_id]
                    mid = ext_line['account_move_id']
                    if mid not in liq_move_ids:
                        acc_key = (ext_line['account_code'], ext_line['account_name'])
                        reconciled_by_move_acc[mid][acc_key] += signed_rec
                        reconciled_totals_by_move[mid] += signed_rec
                        ext_move_currencies[mid] = ext_line.get('company__currency_code')
                        ext_move_companies[mid] = ext_line.get('company_id')

        # Dispatch residual AR/AP lines (True Customer / Supplier Advances)
        for line_info in ar_ap_payment_lines.values():
            dispatch(
                line_info['company_id'],
                line_info['account_code'],
                line_info['account_name'],
                line_info['account_type'],
                line_info['balance'],
                line_info['currency']
            )

        # Allocate across economic lines of each reconciled external commercial move
        if reconciled_totals_by_move:
            ext_lines = list(AccountMoveLine.objects.filter(
                account_move_id__in=list(reconciled_totals_by_move.keys())
            ).values('account_move_id', 'company_id', 'account_code', 'account_name', 'account_type', 'debit', 'credit', 'company__currency_code'))

            ext_lines_by_move = defaultdict(list)
            for el in ext_lines:
                ext_lines_by_move[el['account_move_id']].append(el)

            for mid, total_signed_rec in reconciled_totals_by_move.items():
                lines_in_move = ext_lines_by_move.get(mid, [])
                matched_acc_keys = set(reconciled_by_move_acc[mid].keys())

                matched_ar_ap_lines = [l for l in lines_in_move if (l['account_code'], l['account_name']) in matched_acc_keys]
                non_matched_lines = [l for l in lines_in_move if (l['account_code'], l['account_name']) not in matched_acc_keys]

                orig_ar_ap_total = sum(
                    _to_float(l['debit']) - _to_float(l['credit'])
                    for l in matched_ar_ap_lines
                )

                curr = ext_move_currencies.get(mid) or lines_in_move[0].get('company__currency_code') or effective_base
                cid = ext_move_companies.get(mid) or lines_in_move[0].get('company_id')

                if abs(orig_ar_ap_total) > 0.0001:
                    paid_ratio = total_signed_rec / orig_ar_ap_total

                    for l in non_matched_lines:
                        orig_bal = _to_float(l['debit']) - _to_float(l['credit'])
                        allocated_bal = orig_bal * paid_ratio
                        dispatch(l['company_id'] or cid, l['account_code'], l['account_name'], l['account_type'] or '', allocated_bal, curr)
                else:
                    # Per-Account Zero-Balance Edge Case
                    acc_recs = reconciled_by_move_acc.get(mid, {})
                    for (acode, aname), signed_rec in acc_recs.items():
                        atype = 'asset_receivable' if signed_rec > 0 else 'liability_payable'
                        dispatch(cid, acode, aname, atype, -signed_rec, curr)

        # ── Step 7: Rollforward & Totals ─────────────────────────────────────────────
        cust_adv = CF["operating"]["customer_advances"]
        supp_adv = CF["operating"]["supplier_advances"]
        direct_rec = CF["operating"]["cash_in"]
        direct_paid = CF["operating"]["cash_out"]
        op_total = cust_adv + supp_adv + direct_rec + direct_paid

        inv_in = CF["investing"]["cash_in"]
        inv_out = CF["investing"]["cash_out"]
        inv_total = inv_in + inv_out

        fin_in = CF["financing"]["cash_in"]
        fin_out = CF["financing"]["cash_out"]
        fin_total = fin_in + fin_out

        unclass_in = CF["unclassified"]["cash_in"]
        unclass_out = CF["unclassified"]["cash_out"]
        unclass_total = unclass_in + unclass_out

        classified_net_change = op_total + inv_total + fin_total + unclass_total
        unexplained_difference = actual_net_change - classified_net_change

        return {
            'beginning_balance': beginning_balance,
            'operating_activities': {
                'customer_payments': cust_adv,
                'customer_advances': cust_adv,
                'supplier_payments': supp_adv,
                'supplier_advances': supp_adv,
                'cash_received_from_operating_activities': direct_rec,
                'cash_paid_for_operating_activities': direct_paid,
                'direct_receipts': direct_rec,
                'direct_payments': direct_paid,
                'total': op_total,
            },
            'investing_activities': {
                'cash_in': inv_in,
                'cash_out': inv_out,
                'total': inv_total,
            },
            'financing_activities': {
                'cash_in': fin_in,
                'cash_out': fin_out,
                'total': fin_total,
            },
            'unclassified_activities': {
                'cash_in': unclass_in,
                'cash_out': unclass_out,
                'total': unclass_total,
            },
            'net_increase': classified_net_change,
            'net_change_in_cash': classified_net_change,
            'actual_net_change_in_cash': actual_net_change,
            'unexplained_difference': unexplained_difference,
            'closing_balance': closing_balance,
            'is_validated_fixture': False,
            'source_engine': 'local_ias7_reconciler',
        }

    @classmethod
    def compute(
        cls,
        tenant_id: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        company_ids: Optional[List[int]] = None,
        base_currency: Optional[str] = None,
        tenant_ids: Optional[List[str]] = None,
        source: str = "auto",
    ) -> Dict[str, Any]:
        """
        Unified Dispatcher for Cash Flow Statement:
        source: 'auto' | 'odoo_live' | 'local_engine'
        Supports all 4 dimensions in Live Odoo and Local Engine:
        - Multi-Tenant: tenant_ids / tenant_id
        - Multi-Company: company_ids
        - Target Base Currency: base_currency
        - Time Period: start_date / end_date
        """
        start_time = time.time()
        effective_tid = tenant_id or (tenant_ids[0] if tenant_ids else "")

        if source in ("auto", "odoo_live"):
            try:
                live_res = cls.fetch_live_odoo_cash_flow(
                    tenant=Tenant.objects.filter(id=effective_tid).first() if effective_tid else None,
                    tenant_ids=tenant_ids,
                    start_date=start_date,
                    end_date=end_date,
                    company_ids=company_ids,
                    base_currency=base_currency,
                )
                if live_res:
                    live_res["execution_time_ms"] = round((time.time() - start_time) * 1000, 2)
                    return live_res
            except Exception as e:
                logger.warning(f"Live Odoo Cash Flow fetch failed, falling back to local engine: {e}")
                if source == "odoo_live":
                    raise

        # Fallback to Local IAS 7 Formula Engine
        local_res = cls.compute_local_cash_flow(
            tenant_id=effective_tid,
            start_date=start_date,
            end_date=end_date,
            company_ids=company_ids,
            base_currency=base_currency,
            tenant_ids=tenant_ids,
        )
        local_res["execution_time_ms"] = round((time.time() - start_time) * 1000, 2)
        return local_res

    @classmethod
    def get_drilldown_lines(
        cls,
        tenant_id: str,
        section: str,
        line_key: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        company_ids: Optional[List[int]] = None,
        limit: int = 200,
    ) -> List[Dict[str, Any]]:
        """
        Returns individual contributing journal entries and counterpart items for any Cash Flow section.
        Adheres to Workspace Rule #1 (date synchronization).
        """
        liq_filter = cls.get_liquidity_filter(tenant_ids=[tenant_id] if tenant_id else None)

        period_qs = AccountMove.objects.filter(
            tenant_id=tenant_id,
            state="posted"
        )
        if company_ids:
            period_qs = period_qs.filter(company_id__in=company_ids)
        if start_date:
            period_qs = period_qs.filter(date__gte=start_date)
        if end_date:
            period_qs = period_qs.filter(date__lte=end_date)

        # Filter lines by target section
        sec_lower = section.lower()
        if "operating" in sec_lower:
            target_types = ["asset_receivable", "liability_payable", "income", "expense"]
        elif "investing" in sec_lower:
            target_types = ["asset_fixed", "asset_non_current"]
        elif "financing" in sec_lower:
            target_types = ["equity", "equity_unaffected", "liability_non_current"]
        else:
            target_types = []

        lines_qs = AccountMoveLine.objects.filter(
            account_move__in=period_qs
        ).exclude(liq_filter)

        if target_types:
            lines_qs = lines_qs.filter(account_type__in=target_types)

        lines = lines_qs.select_related("account_move", "partner", "company").order_by("-account_move__date")[:limit]

        drilldown_records = []
        for l in lines:
            move_name = l.account_move.odoo_name if hasattr(l.account_move, 'odoo_name') else getattr(l.account_move, 'name', '')
            drilldown_records.append({
                "move_id": l.account_move_id,
                "move_name": move_name,
                "date": str(l.account_move.date),
                "partner_name": l.partner.name if l.partner else None,
                "account_code": l.account_code,
                "account_name": l.account_name,
                "account_type": l.account_type,
                "debit": float(l.debit or 0),
                "credit": float(l.credit or 0),
                "balance": float(l.balance or 0),
                "company_name": l.company.name if l.company else None,
            })

        return drilldown_records
