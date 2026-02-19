"""
Accounting API service
"""

import asyncio
from typing import List, Optional
from django.db.models import Sum
from odoo_app.models.account_move import AccountMove
from doova_one_view.api.common.exceptions import NotFoundError
from doova_one_view.api.accounting.schemas import (
    AccountMoveRead, AccountMoveWithLinesRead, AccountingSummary, PaginatedResponse
)

class AccountingService:
    """Service for accounting operations"""
    
    @staticmethod
    async def list_moves(
        tenant_id: str,
        limit: int = 50,
        offset: int = 0,
        move_type: Optional[str] = None
    ) -> PaginatedResponse[AccountMoveRead]:
        """List accounting moves for a tenant"""
        def _list():
            qs = AccountMove.objects.filter(tenant_id=tenant_id)
            if move_type:
                qs = qs.filter(move_type=move_type)
            
            total = qs.count()
            qs = qs.select_related('partner', 'company')
            qs = qs.order_by('-date')
            items = list(qs[offset:offset+limit])
            return items, total
        
        moves, total = await asyncio.to_thread(_list)
        return PaginatedResponse(
            items=[AccountMoveRead.model_validate(m) for m in moves],
            total=total,
            limit=limit,
            offset=offset
        )
    
    @staticmethod
    async def get_move(tenant_id: str, move_id: int) -> AccountMoveWithLinesRead:
        """Get a specific move with its lines"""
        def _get():
            try:
                return AccountMove.objects.select_related(
                    'partner', 'company'
                ).prefetch_related(
                    'lines', 'lines__product'
                ).get(
                    tenant_id=tenant_id, id=move_id
                )
            except AccountMove.DoesNotExist:
                raise NotFoundError("AccountMove", str(move_id))
        
        move = await asyncio.to_thread(_get)
        return AccountMoveWithLinesRead.model_validate(move)

    @staticmethod
    async def get_accounting_summary(tenant_id: str) -> AccountingSummary:
        """Get summarized accounting metrics"""
        def _summary():
            # Invoices (Customer)
            invoiced = AccountMove.objects.filter(
                tenant_id=tenant_id, 
                move_type='out_invoice',
                state='posted'
            ).aggregate(
                total=Sum('amount_total'),
                residual=Sum('amount_residual')
            )
            
            # Bills (Vendor)
            bills = AccountMove.objects.filter(
                tenant_id=tenant_id, 
                move_type='in_invoice',
                state='posted'
            ).aggregate(
                total=Sum('amount_total'),
                residual=Sum('amount_residual')
            )
            
            total_invoiced = float(invoiced['total'] or 0)
            total_bills = float(bills['total'] or 0)
            
            return AccountingSummary(
                total_invoiced=total_invoiced,
                total_bills=total_bills,
                total_receivable=float(invoiced['residual'] or 0),
                total_payable=float(bills['residual'] or 0),
                net_profit_estimate=total_invoiced - total_bills
            )
            
        return await asyncio.to_thread(_summary)
