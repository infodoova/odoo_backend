    @staticmethod
    async def get_journal_cards(
        tenant_id: str,
        start_date: str = None,
        end_date: str = None,
        company_ids: list[int] = None,
        base_currency: str = None,
        limit: int = 50,
        offset: int = 0
    ) -> dict[str, Any]:
        def _get():
            from odoo_app.models import AccountJournal, AccountMove, BankStatement, AccountMoveLine
            from django.db.models import Sum, Q, Count, Case, When, F, DecimalField
            from datetime import date
            from doova_one_view.api.kpi.service import _get_rate_map, _get_conversion_rate, _sum_converted
            
            rate_map = _get_rate_map()
            effective_base = (base_currency or "XAF").upper()
            
            qs = AccountJournal.objects.filter(tenant_id=tenant_id)
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
                    tenant_id=tenant_id,
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
                    stmt_qs = BankStatement.objects.filter(tenant_id=tenant_id, journal=j)
                    if start_date:
                        stmt_qs = stmt_qs.filter(date__gte=start_date)
                    if end_date:
                        stmt_qs = stmt_qs.filter(date__lte=end_date)
                    
                    latest_statement = stmt_qs.order_by('-date', '-id').first()
                    
                    if latest_statement:
                        metrics["latest_statement_balance"] = _to_float(latest_statement.balance_end_real) * rate
                        metrics["balance"] = metrics["latest_statement_balance"]
                    
                    gl_qs = AccountMoveLine.objects.filter(
                        tenant_id=tenant_id,
                        account_move__state='posted'
                    )
                    
                    if hasattr(j, 'default_account_code') and j.default_account_code:
                        gl_qs = gl_qs.filter(account_code=j.default_account_code)
                        if j.company_id:
                            gl_qs = gl_qs.filter(company_id=j.company_id)
                    else:
                        gl_qs = gl_qs.filter(account_move__journal=j)
                        
                    if start_date:
                        gl_qs = gl_qs.filter(account_move__date__gte=start_date)
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
                        tenant_id=tenant_id,
                        journal=j,
                        move_type__in=move_types
                    )
                    if start_date:
                        moves_qs = moves_qs.filter(date__gte=start_date)
                    if end_date:
                        moves_qs = moves_qs.filter(date__lte=end_date)
                    
                    # Sign for refunds
                    sign_expr = Case(
                        When(move_type__in=['out_refund', 'in_refund'], then=-1),
                        default=1,
                        output_field=DecimalField()
                    )
                    
                    draft_qs = moves_qs.filter(state='draft').annotate(signed_total=F('amount_total') * sign_expr)
                    metrics["draft_count"] = draft_qs.count()
                    metrics["draft_amount"] = _sum_converted(draft_qs, 'signed_total', effective_base, rate_map)
                    
                    unpaid_qs = moves_qs.filter(state='posted').exclude(payment_state__in=['paid', 'reversed']).annotate(signed_residual=F('amount_residual') * sign_expr)
                    metrics["unpaid_count"] = unpaid_qs.count()
                    metrics["unpaid_amount"] = _sum_converted(unpaid_qs, 'signed_residual', effective_base, rate_map)
                    
                    late_qs = unpaid_qs.filter(invoice_date_due__lt=date.today())
                    metrics["late_count"] = late_qs.count()
                    metrics["late_amount"] = _sum_converted(late_qs, 'signed_residual', effective_base, rate_map)

                else:
                    # General journals: misc. operations, stock, voucher, etc.
                    gen_moves_qs = AccountMove.objects.filter(
                        tenant_id=tenant_id,
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
                        tenant_id=tenant_id,
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
            
        return await asyncio.to_thread(_get)
