# api/agent/tools_refactored/banking.py
from typing import Optional, Any
from doova_one_view.api.accounting.service import AccountingService, _metric, _to_float, _iso
from datetime import date
from django.db.models import Sum, Q, Count, Case, When, F, DecimalField
from doova_one_view.api.kpi.service import _get_rate_map, _get_conversion_rate, _sum_converted
from doova_one_view.api.agent.tools_refactored.common import run_query, normalize_company_ids, build_company_filter_sql
from doova_one_view.api.agent.query_context import build_tenant_filter_sql

def get_dashboard_impl(
    tenant_id: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    company_ids: Optional[list[int]] = None,
    base_currency: Optional[str] = None,
    tenant_ids: Optional[list[str]] = None
) -> dict[str, Any]:
    def _dashboard():
        from doova_one_view.api.agent.query_context import normalize_tenant_ids
        tenants = normalize_tenant_ids(tenant_id=tenant_id, tenant_ids=tenant_ids)

        def _local_base_qs(c_ids):
            from odoo_app.models.account_move import AccountMove
            q = AccountMove.objects.all()
            if tenants:
                q = q.filter(tenant_id__in=tenants)
            if c_ids:
                q = q.filter(company_id__in=c_ids)
            return q

        qs = AccountingService._date_qs(
            _local_base_qs(company_ids), start_date, end_date
        )
        
        rate_map = _get_rate_map()
        effective_base = base_currency or "XAF"
        
        revenue_qs = qs.filter(move_type="out_invoice", state="posted")
        expense_qs = qs.filter(move_type="in_invoice", state="posted")

        posted_qs = qs.filter(state="posted")
        from odoo_app.models.account_move_line import AccountMoveLine
        from django.db.models import Sum
        
        line_aggs = AccountMoveLine.objects.filter(
            account_move__in=posted_qs
        ).values("account_type", "account_code", "company__currency_code").annotate(
            total_debit=Sum("debit"),
            total_credit=Sum("credit")
        )
        
        true_revenue = 0.0
        true_expenses = 0.0
        true_cogs = 0.0
        true_opex = 0.0
        
        for agg in line_aggs:
            atype = agg["account_type"] or ""
            acode = agg["account_code"] or ""
            # Use company currency to convert to dashboard base currency
            company_currency = agg["company__currency_code"] or "COMPANY_BASE"
            rate = _get_conversion_rate(company_currency, effective_base, rate_map)
            
            net_credit = (_to_float(agg["total_credit"]) - _to_float(agg["total_debit"])) * rate
            net_debit = (_to_float(agg["total_debit"]) - _to_float(agg["total_credit"])) * rate
            
            if acode in ("60520003", "60510002"):
                continue

            if atype.startswith("income"):
                true_revenue += net_credit
            elif atype.startswith("expense"):
                true_expenses += net_debit
                if atype == "expense_direct_cost":
                    true_cogs += net_debit
                elif atype in ("expense", "expense_depreciation"):
                    if acode.startswith("67") or acode.startswith("69"):
                        pass  # financial charges + income tax excluded from opex
                    else:
                        true_opex += net_debit

        gross_profit = true_revenue - true_cogs
        ebit = gross_profit - true_opex
        net_profit = true_revenue - true_expenses
        
        cumulative_qs = _local_base_qs(company_ids)
        if end_date:
            cumulative_qs = cumulative_qs.filter(date__lte=end_date)
        cumulative_qs = cumulative_qs.filter(state='posted')
        
        cumulative_aggs = AccountMoveLine.objects.filter(
            account_move__in=cumulative_qs,
            account_type__in=["asset_receivable", "liability_payable", "liability_current", "asset_cash"]
        ).values("account_type", "company__currency_code").annotate(
            total_debit=Sum("debit"),
            total_credit=Sum("credit")
        )
        
        receivable_balance = 0.0
        payable_balance = 0.0
        bank_balance = 0.0
        
        for agg in cumulative_aggs:
            company_currency = agg["company__currency_code"] or "COMPANY_BASE"
            rate = _get_conversion_rate(company_currency, effective_base, rate_map)
            net = (_to_float(agg["total_debit"]) - _to_float(agg["total_credit"])) * rate
            if agg["account_type"] == "asset_receivable":
                receivable_balance += net
            elif agg["account_type"] in ("liability_payable", "liability_current"):
                payable_balance -= net # payables are credit normal
            elif agg["account_type"] == "asset_cash":
                bank_balance += net

        # --- Bank & Cash Balances Details ---
        opening_cash_balance = 0.0
        cash_in = 0.0
        cash_out = 0.0
        
        # Opening balance (moves strictly before start_date)
        if start_date:
            opening_qs = _local_base_qs(company_ids).filter(
                date__lt=start_date, state='posted'
            )
            opening_aggs = AccountMoveLine.objects.filter(
                account_move__in=opening_qs,
                account_type="asset_cash"
            ).values("company__currency_code").annotate(
                net_cash=Sum("debit") - Sum("credit")
            )
            for agg in opening_aggs:
                comp_curr = agg["company__currency_code"] or "COMPANY_BASE"
                rate = _get_conversion_rate(comp_curr, effective_base, rate_map)
                opening_cash_balance += _to_float(agg["net_cash"]) * rate
        else:
            opening_cash_balance = 0.0 # If all-time, opening is 0

        # Cash In & Out (moves within the date range)
        period_qs = AccountingService._date_qs(
            _local_base_qs(company_ids), start_date, end_date
        ).filter(state='posted')
        period_aggs = AccountMoveLine.objects.filter(
            account_move__in=period_qs,
            account_type="asset_cash"
        ).values("company__currency_code").annotate(
            total_debit=Sum("debit"),
            total_credit=Sum("credit")
        )
        for agg in period_aggs:
            comp_curr = agg["company__currency_code"] or "COMPANY_BASE"
            rate = _get_conversion_rate(comp_curr, effective_base, rate_map)
            
            # In Odoo, for asset accounts, Debit is Increase (In), Credit is Decrease (Out)
            cash_in += _to_float(agg["total_debit"]) * rate
            cash_out += _to_float(agg["total_credit"]) * rate

        today = date.today()
        overdue_filter = Q(invoice_date_due__lt=today) & ~Q(payment_state__in=["paid", "reversed"])
        
        # Note: overdue amounts still rely on invoice residuals but look at ALL invoices up to end_date
        # because 'amount_residual' is an invoice-level field, not easily derived from generic move lines.
        overdue_receivable = _sum_converted(
            cumulative_qs.filter(overdue_filter, move_type="out_invoice", amount_residual__gt=0),
            "amount_residual", effective_base, rate_map
        )
        overdue_payable = _sum_converted(
            cumulative_qs.filter(overdue_filter, move_type="in_invoice", amount_residual__gt=0),
            "amount_residual", effective_base, rate_map
        )

        rev_cust_map = {}
        for r in revenue_qs.filter(partner_id__isnull=False).values("partner_id", "partner__name", "currency_code").annotate(value=Sum("amount_total")):
            pid = r['partner_id']
            if pid not in rev_cust_map:
                rev_cust_map[pid] = {'name': r['partner__name'], 'value': 0.0}
            code = r['currency_code'] or "COMPANY_BASE"
            rev_cust_map[pid]['value'] += _to_float(r['value']) * _get_conversion_rate(code, effective_base, rate_map)
        top_revenue_customers = [
            {"id": k, "name": v['name'] or "", "value": v['value']}
            for k, v in sorted(rev_cust_map.items(), key=lambda x: x[1]['value'], reverse=True)[:5]
        ]
        
        exp_vend_map = {}
        for r in expense_qs.filter(partner_id__isnull=False).values("partner_id", "partner__name", "currency_code").annotate(value=Sum("amount_total")):
            pid = r['partner_id']
            if pid not in exp_vend_map:
                exp_vend_map[pid] = {'name': r['partner__name'], 'value': 0.0}
            code = r['currency_code'] or "COMPANY_BASE"
            exp_vend_map[pid]['value'] += _to_float(r['value']) * _get_conversion_rate(code, effective_base, rate_map)
        top_expense_vendors = [
            {"id": k, "name": v['name'] or "", "value": v['value']}
            for k, v in sorted(exp_vend_map.items(), key=lambda x: x[1]['value'], reverse=True)[:5]
        ]

        trend_aggs = AccountMoveLine.objects.filter(
            account_move__in=posted_qs
        ).values("account_move__date", "account_type", "company__currency_code").annotate(
            total_debit=Sum("debit"),
            total_credit=Sum("credit")
        )
        
        revenue_trend_map = {}
        expense_trend_map = {}
        cash_flow_map = {}
        
        for row in trend_aggs:
            if not row["account_move__date"]: continue
            d_str = _iso(row["account_move__date"])
            company_currency = row["company__currency_code"] or "COMPANY_BASE"
            rate = _get_conversion_rate(company_currency, effective_base, rate_map)
            
            net_credit = (_to_float(row["total_credit"]) - _to_float(row["total_debit"])) * rate
            net_debit = (_to_float(row["total_debit"]) - _to_float(row["total_credit"])) * rate
            
            atype = row["account_type"] or ""
            
            if atype.startswith("income"):
                revenue_trend_map[d_str] = revenue_trend_map.get(d_str, 0.0) + net_credit
            elif atype.startswith("expense"):
                expense_trend_map[d_str] = expense_trend_map.get(d_str, 0.0) + net_debit
                
            if atype in ["asset_cash", "liability_credit_card"]:
                cash_flow_map[d_str] = cash_flow_map.get(d_str, 0.0) + net_debit # debit increases cash

        revenue_trend = [{"date": d, "value": v} for d, v in sorted(revenue_trend_map.items())]
        expense_trend = [{"date": d, "value": v} for d, v in sorted(expense_trend_map.items())]
        cash_flow_trend = [{"date": d, "value": v} for d, v in sorted(cash_flow_map.items())]



        state_distribution = {
            row["state"] or "unknown": row["count"]
            for row in qs.values("state").annotate(count=Count("id"))
        }
        payment_state_distribution = {
            row["payment_state"] or "unknown": row["count"]
            for row in qs.values("payment_state").annotate(count=Count("id"))
        }
        move_type_distribution = {
            row["move_type"] or "unknown": row["count"]
            for row in qs.values("move_type").annotate(count=Count("id"))
        }

        receivables_aging = AccountingService._aging(qs, "out_invoice", effective_base, rate_map)
        payables_aging = AccountingService._aging(qs, "in_invoice", effective_base, rate_map)

        net_profit_margin_pct = (net_profit / true_revenue * 100) if true_revenue else 0.0
        
        # Calculate total cash flow from the trend array
        total_cash_flow = sum(item["value"] for item in cash_flow_trend)
        
        # --- Deep Cash Flow Tracing (Breakdown) ---
        from django.db import connection
        cash_flow_breakdown_map = {}
        with connection.cursor() as cursor:
            sql = """
                SELECT 
                    pay_line.id as cash_line_id,
                    pay_line.debit - pay_line.credit as cash_amount,
                    comp.currency_code,
                    
                    -- === Zero-Step ===
                    m1_inc_line.id as m1_inc_id,
                    m1_inc_line.account_name as m1_account_name,
                    ABS(m1_inc_line.balance) as m1_inc_balance,
                    
                    -- === One-Step ===
                    recon1.id as recon1_id,
                    recon1.amount as recon1_amount,
                    m2_line.id as m2_line_id,
                    ABS(m2_line.balance) as m2_line_balance,
                    m2_inc_line.id as m2_inc_id,
                    m2_inc_line.account_name as m2_account_name,
                    ABS(m2_inc_line.balance) as m2_inc_balance,
                    
                    -- === Two-Step ===
                    recon2.id as recon2_id,
                    recon2.amount as recon2_amount,
                    m3_line.id as m3_line_id,
                    ABS(m3_line.balance) as m3_ar_balance,
                    m3_inc_line.id as m3_inc_id,
                    m3_inc_line.account_name as m3_account_name,
                    ABS(m3_inc_line.balance) as m3_inc_balance
                    
                FROM fact_account_move_lines pay_line
                JOIN fact_account_moves pay_move ON pay_line.account_move_id = pay_move.id
                LEFT JOIN dim_companies comp ON pay_line.company_id = comp.id
                
                -- FIND COUNTERPART (Outstanding or AR/AP)
                LEFT JOIN fact_account_move_lines pay_cp_line 
                    ON pay_cp_line.account_move_id = pay_move.id 
                    AND pay_cp_line.id != pay_line.id
                    AND pay_cp_line.account_type IN ('asset_receivable', 'liability_payable', 'asset_current', 'asset_cash')
                    
                -- ZERO-STEP (Direct Cash Expense/Income)
                LEFT JOIN fact_account_move_lines m1_inc_line
                    ON m1_inc_line.account_move_id = pay_move.id
                    AND m1_inc_line.id != pay_line.id
                    AND m1_inc_line.account_type NOT IN ('asset_receivable', 'liability_payable', 'asset_cash')
                    
                -- JUMP 1
                LEFT JOIN fact_account_partial_reconciles recon1
                    ON (pay_cp_line.id = recon1.debit_move_line_id OR pay_cp_line.id = recon1.credit_move_line_id)
                    
                LEFT JOIN fact_account_move_lines m2_line
                    ON (m2_line.id = recon1.debit_move_line_id OR m2_line.id = recon1.credit_move_line_id)
                    AND m2_line.id != pay_cp_line.id
                    
                -- One-Step target: Is Move 2 the Invoice?
                LEFT JOIN fact_account_move_lines m2_inc_line
                    ON m2_inc_line.account_move_id = m2_line.account_move_id
                    AND m2_inc_line.id != m2_line.id
                    AND m2_inc_line.account_type NOT IN ('asset_receivable', 'liability_payable', 'asset_cash')

                -- JUMP 2
                -- If Move 2 was a Payment, it has an AR/AP line to reconcile with the Invoice
                LEFT JOIN fact_account_move_lines m2_ar_line
                    ON m2_ar_line.account_move_id = m2_line.account_move_id
                    AND m2_ar_line.id != m2_line.id
                    AND m2_ar_line.account_type IN ('asset_receivable', 'liability_payable')
                    
                LEFT JOIN fact_account_partial_reconciles recon2
                    ON (m2_ar_line.id = recon2.debit_move_line_id OR m2_ar_line.id = recon2.credit_move_line_id)
                    
                LEFT JOIN fact_account_move_lines m3_line
                    ON (m3_line.id = recon2.debit_move_line_id OR m3_line.id = recon2.credit_move_line_id)
                    AND m3_line.id != m2_ar_line.id
                    
                -- Two-Step target: Income on Move 3
                LEFT JOIN fact_account_move_lines m3_inc_line
                    ON m3_inc_line.account_move_id = m3_line.account_move_id
                    AND m3_inc_line.id != m3_line.id
                    AND m3_inc_line.account_type NOT IN ('asset_receivable', 'liability_payable', 'asset_cash')
                    
                WHERE 1=1
                  AND pay_line.account_type = 'asset_cash'
                  AND pay_move.state = 'posted'
            """
            params = []
            if tenants:
                if len(tenants) == 1:
                    sql += " AND pay_line.tenant_id = %s"
                    params.append(tenants[0])
                else:
                    placeholders = ','.join(['%s'] * len(tenants))
                    sql += f" AND pay_line.tenant_id IN ({placeholders})"
                    params.extend(tenants)
            
            if start_date:
                sql += " AND pay_move.date >= %s"
                params.append(start_date)
            if end_date:
                sql += " AND pay_move.date <= %s"
                params.append(end_date)
            if company_ids:
                placeholders = ','.join(['%s'] * len(company_ids))
                sql += f" AND pay_line.company_id IN ({placeholders})"
                params.extend(company_ids)
                
            cursor.execute(sql, params)
            columns = [col[0] for col in cursor.description]
            
            # Track by cash line to handle un-reconciled remainders
            cash_lines = {}
            
            for row in cursor.fetchall():
                d = dict(zip(columns, row))
                c_id = d['cash_line_id']
                if c_id not in cash_lines:
                    cash_lines[c_id] = {
                        'amount': _to_float(d['cash_amount']),
                        'currency': d['currency_code'] or 'COMPANY_BASE',
                        'm1_inc_lines': {},
                        'recon1s': {}
                    }
                    
                c_info = cash_lines[c_id]
                
                if d['m1_inc_id']:
                    c_info['m1_inc_lines'][d['m1_inc_id']] = {
                        'cat': d['m1_account_name'],
                        'balance': _to_float(d['m1_inc_balance'] or 0)
                    }
                    
                if d['recon1_id']:
                    r1_id = d['recon1_id']
                    if r1_id not in c_info['recon1s']:
                        c_info['recon1s'][r1_id] = {
                            'amount': _to_float(d['recon1_amount'] or 0),
                            'm2_line_balance': _to_float(d['m2_line_balance'] or 0),
                            'm2_inc_lines': {},
                            'recon2s': {}
                        }
                    r1_info = c_info['recon1s'][r1_id]
                    
                    if d['m2_inc_id']:
                        r1_info['m2_inc_lines'][d['m2_inc_id']] = {
                            'cat': d['m2_account_name'],
                            'balance': _to_float(d['m2_inc_balance'] or 0)
                        }
                        
                    if d['recon2_id']:
                        r2_id = d['recon2_id']
                        if r2_id not in r1_info['recon2s']:
                            r1_info['recon2s'][r2_id] = {
                                'amount': _to_float(d['recon2_amount'] or 0),
                                'm3_ar_balance': _to_float(d['m3_ar_balance'] or 0),
                                'm3_inc_lines': {}
                            }
                        r2_info = r1_info['recon2s'][r2_id]
                        
                        if d['m3_inc_id']:
                            r2_info['m3_inc_lines'][d['m3_inc_id']] = {
                                'cat': d['m3_account_name'],
                                'balance': _to_float(d['m3_inc_balance'] or 0)
                            }

            # Process allocations
            for c_id, info in cash_lines.items():
                total_abs = abs(info['amount'])
                sign = 1 if info['amount'] > 0 else -1
                explained_abs = 0.0
                rate = _get_conversion_rate(info['currency'], effective_base, rate_map)
                
                for r1_id, r1_info in info['recon1s'].items():
                    r1_amt = r1_info['amount']
                    if r1_amt == 0: continue
                    
                    explained_abs += r1_amt
                    
                    if r1_info['m2_inc_lines']:
                        m2_ar_bal = r1_info['m2_line_balance']
                        if m2_ar_bal > 0:
                            for m2_inc_id, m2_inc in r1_info['m2_inc_lines'].items():
                                ratio = m2_inc['balance'] / m2_ar_bal
                                allocated = r1_amt * ratio * sign
                                cat = m2_inc['cat'] or 'Unknown'
                                cash_flow_breakdown_map[cat] = cash_flow_breakdown_map.get(cat, 0.0) + (allocated * rate)
                                
                    elif r1_info['recon2s']:
                        m2_line_bal = r1_info['m2_line_balance']
                        if m2_line_bal > 0:
                            funding_ratio = r1_amt / m2_line_bal
                            
                            for r2_id, r2_info in r1_info['recon2s'].items():
                                invoice_funded = r2_info['amount'] * funding_ratio
                                m3_ar_bal = r2_info['m3_ar_balance']
                                if m3_ar_bal > 0:
                                    for m3_inc_id, m3_inc in r2_info['m3_inc_lines'].items():
                                        inc_ratio = m3_inc['balance'] / m3_ar_bal
                                        allocated = invoice_funded * inc_ratio * sign
                                        cat = m3_inc['cat'] or 'Unknown'
                                        cash_flow_breakdown_map[cat] = cash_flow_breakdown_map.get(cat, 0.0) + (allocated * rate)
                    else:
                        cat = 'Unreconciled Cash Entry'
                        cash_flow_breakdown_map[cat] = cash_flow_breakdown_map.get(cat, 0.0) + (r1_amt * sign * rate)

                unreconciled_abs = total_abs - explained_abs
                if unreconciled_abs > 0.01:
                    if info['m1_inc_lines']:
                        total_m1_bal = sum(m1['balance'] for m1 in info['m1_inc_lines'].values())
                        if total_m1_bal > 0:
                            for m1_inc_id, m1_inc in info['m1_inc_lines'].items():
                                ratio = m1_inc['balance'] / total_m1_bal
                                allocated = unreconciled_abs * ratio * sign
                                cat = m1_inc['cat'] or 'Unknown'
                                cash_flow_breakdown_map[cat] = cash_flow_breakdown_map.get(cat, 0.0) + (allocated * rate)
                        else:
                            cat = 'Unreconciled Cash Entry'
                            cash_flow_breakdown_map[cat] = cash_flow_breakdown_map.get(cat, 0.0) + (unreconciled_abs * sign * rate)
                    else:
                        cat = 'Unreconciled Cash Entry'
                        cash_flow_breakdown_map[cat] = cash_flow_breakdown_map.get(cat, 0.0) + (unreconciled_abs * sign * rate)
        
        # Format breakdown for output
        cash_flow_breakdown = [
            {"category": cat, "value": val} 
            for cat, val in sorted(cash_flow_breakdown_map.items(), key=lambda x: abs(x[1]), reverse=True)
        ]
        
        applied = {
            "tenant_id": tenant_id,
            "start_date": start_date,
            "end_date": end_date,
            "company_ids": company_ids,
        }
        
        # --- Intelligent Alerts Engine ---
        alerts = []
        
        # 1. Receivables Aging Alert (>25% over 90 days)
        total_recv = sum(b.get("amount", 0.0) for b in receivables_aging)
        over_90_recv = 0.0
        for bucket in receivables_aging:
            if bucket.get("bucket") == "90+":
                over_90_recv = bucket.get("amount", 0.0)
        if total_recv > 0 and (over_90_recv / total_recv) > 0.25:
            alerts.append({
                "severity": "high",
                "type": "receivables_aging",
                "message": f"High risk: {over_90_recv / total_recv:.0%} of your unpaid receivables are older than 90 days."
            })
            
        # 2. Expense Spike Alert (>3x average daily)
        if expense_trend:
            avg_expense = sum(d["value"] for d in expense_trend) / len(expense_trend)
            if avg_expense > 0:
                for d in expense_trend:
                    if d["value"] > avg_expense * 3 and d["value"] > 1000:
                        alerts.append({
                            "severity": "medium",
                            "type": "expense_spike",
                            "message": f"Expenses spiked sharply on {d['date']} to {d['value']:,.0f}."
                        })
                        break
                        
        # 3. Vendor Concentration Alert (>40% total expenses)
        if top_expense_vendors and true_expenses > 0:
            top_vendor = top_expense_vendors[0]
            if (top_vendor["value"] / true_expenses) > 0.40:
                alerts.append({
                    "severity": "medium",
                    "type": "vendor_concentration",
                    "message": f"Vendor concentration: '{top_vendor['name']}' represents {top_vendor['value'] / true_expenses:.0%} of your total expenses."
                })
                
        # 4. Cash Flow Drop Alert (>3x negative average)
        negative_flows = [d["value"] for d in cash_flow_trend if d["value"] < 0]
        if negative_flows:
            avg_negative = sum(negative_flows) / len(negative_flows)
            for d in cash_flow_trend:
                if d["value"] < avg_negative * 3:
                    alerts.append({
                        "severity": "medium",
                        "type": "cash_flow_drop",
                        "message": f"Significant cash flow drop observed on {d['date']} ({d['value']:,.0f})."
                    })
                    break

        return {
            "total_revenue": _metric(true_revenue),
            "total_expenses": _metric(true_expenses),
            "net_profit": _metric(net_profit),
            "net_cash_flow": _metric(total_cash_flow),
            "gross_profit": _metric(gross_profit),
            "ebit": _metric(ebit),
            "net_profit_margin_pct": net_profit_margin_pct,
            "bank_balance": bank_balance,
            "opening_cash_balance": opening_cash_balance,
            "cash_in": cash_in,
            "cash_out": cash_out,
            "closing_cash_balance": opening_cash_balance + cash_in - cash_out,
            "receivable_balance": receivable_balance,
            "overdue_receivable": overdue_receivable,
            "payable_balance": payable_balance,
            "overdue_payable": overdue_payable,
            "top_revenue_customers": top_revenue_customers,
            "top_expense_vendors": top_expense_vendors,
            "revenue_trend": revenue_trend,
            "expense_trend": expense_trend,
            "cash_flow_trend": cash_flow_trend,
            "cash_flow_breakdown": cash_flow_breakdown,
            "state_distribution": state_distribution,
            "payment_state_distribution": payment_state_distribution,
            "payment_status_distribution": payment_state_distribution,
            "move_type_distribution": move_type_distribution,
            "receivables_aging": receivables_aging,
            "payables_aging": payables_aging,
            "ar_aging": receivables_aging,
            "ap_aging": payables_aging,
            "alerts": alerts,
            "applied_filters": applied,
        }

    return _dashboard()


def get_journal_cards_impl(
    tenant_id: str,
    start_date: str = None,
    end_date: str = None,
    company_ids: list[int] = None,
    base_currency: str = None,
    limit: int = 50,
    offset: int = 0,
    tenant_ids: Optional[list[str]] = None
) -> dict:
    def _get():
        from doova_one_view.api.agent.query_context import normalize_tenant_ids
        tenants = normalize_tenant_ids(tenant_id=tenant_id, tenant_ids=tenant_ids)

        from odoo_app.models import AccountJournal, AccountMove, BankStatement, AccountMoveLine
        from django.db.models import Sum, Q, Count, Case, When, F, DecimalField
        from datetime import date
        from doova_one_view.api.kpi.service import _get_rate_map, _get_conversion_rate, _sum_converted
        
        rate_map = _get_rate_map()
        effective_base = (base_currency or "XAF").upper()
        
        qs = AccountJournal.objects.all()
        if tenants:
            qs = qs.filter(tenant_id__in=tenants)
        if company_ids:
            qs = qs.filter(company_id__in=company_ids)
            
        total = qs.count()
        journals = qs.select_related('company').order_by('name')[offset:offset+limit]
        
        cards = []
        for j in journals:
            company_currency = j.company.currency_code if (j.company and j.company.currency_code) else "COMPANY_BASE"
            if not company_currency or company_currency == "COMPANY_BASE":
                company_currency = "XAF"
            
            # Default rate for non-residual items (balances)
            rate = _get_conversion_rate(company_currency, effective_base, rate_map)
            
            metrics = {
                "balance": 0.0,
                "latest_statement_balance": 0.0,
                "gl_balance": 0.0,
                "outstanding_payments": 0.0,
                "outstanding_receipts": 0.0,
                "unpaid_count": 0,
                "unpaid_amount": 0.0,
                "draft_count": 0,
                "draft_amount": 0.0,
                "late_count": 0,
                "late_amount": 0.0,
                "misc_operations_count": 0,
                "misc_operations_amount": 0.0
            }
            
            # Fetch misc operations
            all_misc_qs = AccountMove.objects.filter(
                tenant_id__in=tenants,
                journal=j,
                state='posted',
                move_type='entry'
            )
            if start_date:
                all_misc_qs = all_misc_qs.filter(date__gte=start_date)
            if end_date:
                all_misc_qs = all_misc_qs.filter(date__lte=end_date)
            
            misc_all_agg = all_misc_qs.aggregate(
                count=Count('id'),
                amount=Sum('amount_total')
            )
            metrics["misc_operations_count"] = misc_all_agg['count'] or 0
            metrics["misc_operations_amount"] = _to_float(misc_all_agg['amount']) * rate
            
            j_type = j.type or "general"
            
            if j_type in ["bank", "cash"]:
                stmt_qs = BankStatement.objects.filter(tenant_id__in=tenants, journal=j)
                if end_date:
                    stmt_qs = stmt_qs.filter(date__lte=end_date)
                
                latest_statement = stmt_qs.order_by('-date', '-id').first()
                
                if latest_statement:
                    metrics["latest_statement_balance"] = _to_float(latest_statement.balance_end_real) * rate
                    metrics["balance"] = metrics["latest_statement_balance"]
                
                gl_qs = AccountMoveLine.objects.filter(
                    tenant_id__in=tenants,
                    account_move__state='posted'
                )
                
                if hasattr(j, 'default_account_code') and j.default_account_code:
                    gl_qs = gl_qs.filter(account_code=j.default_account_code)
                    if j.company_id:
                        gl_qs = gl_qs.filter(company_id=j.company_id)
                else:
                    gl_qs = gl_qs.filter(account_move__journal=j)
                    
                if end_date:
                    gl_qs = gl_qs.filter(account_move__date__lte=end_date)
                    
                gl_agg = gl_qs.aggregate(
                    total_debit=Sum('debit'),
                    total_credit=Sum('credit')
                )
                metrics["gl_balance"] = (_to_float(gl_agg['total_debit']) - _to_float(gl_agg['total_credit'])) * rate
                
                if not latest_statement:
                    metrics["balance"] = metrics["gl_balance"]
                    
                if hasattr(j, 'default_account_code') and j.default_account_code:
                    journal_own_qs = gl_qs.filter(account_move__journal=j)
                    journal_own_agg = journal_own_qs.aggregate(
                        total_debit=Sum('debit'),
                        total_credit=Sum('credit')
                    )
                    journal_own_bal = (_to_float(journal_own_agg['total_debit']) - _to_float(journal_own_agg['total_credit'])) * rate
                else:
                    journal_own_bal = metrics["gl_balance"]
                    
                metrics["misc_operations_amount"] = metrics["gl_balance"] - journal_own_bal
                
            elif j_type in ["sale", "purchase"]:
                move_types = ['out_invoice', 'out_refund'] if j_type == "sale" else ['in_invoice', 'in_refund']
                
                moves_qs = AccountMove.objects.filter(
                    tenant_id__in=tenants,
                    journal=j,
                    move_type__in=move_types
                )
                if start_date:
                    moves_qs = moves_qs.filter(date__gte=start_date)
                if end_date:
                    moves_qs = moves_qs.filter(date__lte=end_date)
                
                draft_qs = moves_qs.filter(state='draft')
                draft_agg = draft_qs.aggregate(total=Sum('amount_total_signed'))
                metrics["draft_count"] = draft_qs.count()
                metrics["draft_amount"] = abs(_to_float(draft_agg['total'])) * rate
                
                unpaid_qs = moves_qs.filter(state='posted').exclude(payment_state__in=['paid', 'reversed'])
                unpaid_agg = unpaid_qs.aggregate(total=Sum('amount_residual_signed'))
                metrics["unpaid_count"] = unpaid_qs.count()
                metrics["unpaid_amount"] = abs(_to_float(unpaid_agg['total'])) * rate
                
                late_qs = unpaid_qs.filter(invoice_date_due__lt=date.today())
                late_agg = late_qs.aggregate(total=Sum('amount_residual_signed'))
                metrics["late_count"] = late_qs.count()
                metrics["late_amount"] = abs(_to_float(late_agg['total'])) * rate

            else:
                # General journals: misc. operations, stock, voucher, etc.
                gen_moves_qs = AccountMove.objects.filter(
                    tenant_id__in=tenants,
                    journal=j
                )
                if start_date:
                    gen_moves_qs = gen_moves_qs.filter(date__gte=start_date)
                if end_date:
                    gen_moves_qs = gen_moves_qs.filter(date__lte=end_date)

                draft_agg = gen_moves_qs.filter(state='draft').aggregate(
                    count=Count('id'),
                    amount=Sum('amount_total')
                )
                metrics["draft_count"] = draft_agg['count'] or 0
                metrics["draft_amount"] = _to_float(draft_agg['amount']) * rate

                gl_qs = AccountMoveLine.objects.filter(
                    tenant_id__in=tenants,
                    account_move__journal=j,
                    account_move__state='posted'
                )
                if start_date:
                    gl_qs = gl_qs.filter(account_move__date__gte=start_date)
                if end_date:
                    gl_qs = gl_qs.filter(account_move__date__lte=end_date)

                gl_agg = gl_qs.aggregate(
                    total_debit=Sum('debit'),
                    total_credit=Sum('credit')
                )
                metrics["gl_balance"] = (_to_float(gl_agg['total_debit']) - _to_float(gl_agg['total_credit'])) * rate

                posted_agg = gen_moves_qs.filter(state='posted').aggregate(
                    count=Count('id'),
                    amount=Sum('amount_total')
                )
                metrics["balance"] = _to_float(posted_agg['amount']) * rate
                metrics["unpaid_count"] = posted_agg['count'] or 0
                metrics["unpaid_amount"] = _to_float(posted_agg['amount']) * rate

            cards.append({
                "id": j.odoo_id,
                "name": j.name,
                "code": j.code,
                "type": j.type,
                "currency_code": j.currency_code or company_currency,
                "company_id": j.company.odoo_id if j.company else None,
                "company_name": j.company.name if j.company else None,
                "metrics": metrics
            })
            
        return {
            "items": cards,
            "total": total,
            "limit": limit,
            "offset": offset,
            "base_currency": effective_base
        }
        
    return _get()


def get_bank_cash_summary_tool(
    tenant_id: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    company_id: Optional[int] = None,
    company_ids: Optional[list[int]] = None,
    base_currency: Optional[str] = None,
    tenant_ids: Optional[list[str]] = None
) -> dict:
    selected = normalize_company_ids(company_id=company_id, companies=company_ids)
    data = get_dashboard_impl(
        tenant_id=tenant_id,
        start_date=start_date,
        end_date=end_date,
        company_ids=selected,
        base_currency=base_currency,
        tenant_ids=tenant_ids
    )
    return {
        "tool_name": "get_bank_cash_summary_tool",
        "opening_cash_balance": data.get("opening_cash_balance", 0.0),
        "cash_in": data.get("cash_in", 0.0),
        "cash_out": data.get("cash_out", 0.0),
        "closing_cash_balance": data.get("closing_cash_balance", 0.0),
        "bank_balance": data.get("bank_balance", 0.0),
        "cash_flow_breakdown": data.get("cash_flow_breakdown", [])
    }

def get_journal_cards_tool(
    tenant_id: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    company_id: Optional[int] = None,
    company_ids: Optional[list[int]] = None,
    base_currency: Optional[str] = None,
    tenant_ids: Optional[list[str]] = None
) -> dict:
    selected = normalize_company_ids(company_id=company_id, companies=company_ids)
    res = get_journal_cards_impl(
        tenant_id=tenant_id,
        start_date=start_date,
        end_date=end_date,
        company_ids=selected,
        base_currency=base_currency,
        tenant_ids=tenant_ids
    )
    return {
        "tool_name": "get_journal_cards_tool",
        "data": res
    }

def get_bank_statement_summary_tool(
    tenant_id: str,
    company_id: Optional[int] = None,
    company_ids: Optional[list[int]] = None,
    tenant_ids: Optional[list[str]] = None
) -> dict:
    selected = normalize_company_ids(company_id=company_id, companies=company_ids)
    
    t_sql, params = build_tenant_filter_sql(tenant_id, tenant_ids, prefix="t", column_name="s.tenant_id")
    c_sql, c_params = build_company_filter_sql(tenant_id, selected, column_name="s.company_id", prefix="company")
    params.update(c_params)

    rows = run_query(f"""
        SELECT 
            s.odoo_name AS statement_name, 
            s.date, 
            s.balance_start, 
            s.balance_end_real, 
            s.currency_code
        FROM fact_bank_statements s
        WHERE 1=1 {t_sql} {c_sql}
        ORDER BY s.date DESC
        LIMIT 20
    """, params)

    return {
        "tool_name": "get_bank_statement_summary_tool",
        "recent_statements": [
            {
                "statement": str(r.get("statement_name")),
                "date": str(r.get("date")),
                "opening_balance": float(r.get("balance_start") or 0),
                "closing_balance": float(r.get("balance_end_real") or 0),
                "currency": str(r.get("currency_code") or "")
            }
            for r in rows
        ]
    }

