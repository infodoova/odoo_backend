                limit=limit,
                offset=offset,
            ).model_dump()
            
        return await asyncio.to_thread(_get)

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
            from django.db.models import Sum, Q, Count
            from datetime import date
            
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
                    "late_amount": 0.0
                }
                
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
                    
                    if hasattr(j, 'default_account_code') and j.default_account_code:
                        gl_qs = AccountMoveLine.objects.filter(
                            tenant_id=tenant_id,
                            account_code=j.default_account_code,
                            account_move__state='posted'
                        )
                    else:
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
                    
                    if not latest_statement:
                        metrics["balance"] = metrics["gl_balance"]
                    
                elif j_type in ["sale", "purchase"]:
                    move_type_filter = "out_invoice" if j_type == "sale" else "in_invoice"
                    
                    moves_qs = AccountMove.objects.filter(
                        tenant_id=tenant_id,
                        journal=j,
                        move_type=move_type_filter
                    )
                    if start_date:
                        moves_qs = moves_qs.filter(date__gte=start_date)
                    if end_date:
                        moves_qs = moves_qs.filter(date__lte=end_date)
                    
                    draft_agg = moves_qs.filter(state='draft').aggregate(
                        count=Count('id'),
                        amount=Sum('amount_total')
                    )
                    metrics["draft_count"] = draft_agg['count'] or 0
                    metrics["draft_amount"] = _to_float(draft_agg['amount']) * rate
                    
                    unpaid_qs = moves_qs.filter(state='posted').exclude(payment_state__in=['paid', 'reversed'])
                    unpaid_agg = unpaid_qs.aggregate(
                        count=Count('id'),
                        amount=Sum('amount_residual')
                    )
                    metrics["unpaid_count"] = unpaid_agg['count'] or 0
                    metrics["unpaid_amount"] = _to_float(unpaid_agg['amount']) * rate
                    
                    late_agg = unpaid_qs.filter(invoice_date_due__lt=date.today()).aggregate(
                        count=Count('id'),
                        amount=Sum('amount_residual')
                    )
                    metrics["late_count"] = late_agg['count'] or 0
                    metrics["late_amount"] = _to_float(late_agg['amount']) * rate

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

                    # Draft entries
                    draft_agg = gen_moves_qs.filter(state='draft').aggregate(
                        count=Count('id'),
                        amount=Sum('amount_total')
                    )
                    metrics["draft_count"] = draft_agg['count'] or 0
                    metrics["draft_amount"] = _to_float(draft_agg['amount']) * rate

                    # GL balance (net debit - credit) from posted move lines
                    gl_qs = AccountMoveLine.objects.filter(
                        tenant_id=tenant_id,