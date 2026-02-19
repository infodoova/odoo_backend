"""
Purchase API service
"""

import asyncio
from typing import List, Optional
from django.db.models import Sum, Avg, Count, Prefetch
from odoo_app.models.purchase_order import PurchaseOrder
from odoo_app.models.purchase_order_line import PurchaseOrderLine
from doova_one_view.api.common.exceptions import NotFoundError
from doova_one_view.api.purchase.schemas import (
    PurchaseOrderRead, PurchaseOrderWithLinesRead, PurchaseSummary, PaginatedResponse
)

class PurchaseService:
    """Service for purchase operations"""
    
    @staticmethod
    async def list_orders(
        tenant_id: str,
        limit: int = 50,
        offset: int = 0,
        partner_id: Optional[int] = None
    ) -> PaginatedResponse[PurchaseOrderRead]:
        """List purchase orders for a tenant"""
        def _list():
            qs = PurchaseOrder.objects.filter(tenant_id=tenant_id)
            if partner_id:
                qs = qs.filter(partner_id=partner_id)
            
            total = qs.count()
            qs = qs.select_related('partner', 'user', 'company')
            qs = qs.order_by('-date_order')
            items = list(qs[offset:offset+limit])
            return items, total
        
        orders, total = await asyncio.to_thread(_list)
        return PaginatedResponse(
            items=[PurchaseOrderRead.model_validate(o) for o in orders],
            total=total,
            limit=limit,
            offset=offset
        )
    
    @staticmethod
    async def get_order(tenant_id: str, order_id: int) -> PurchaseOrderWithLinesRead:
        """Get a specific purchase order with its lines"""
        def _get():
            try:
                # Optimized fetching: prefetch lines and their related products in one go
                return PurchaseOrder.objects.select_related(
                    'partner', 'user', 'company'
                ).prefetch_related(
                    Prefetch('lines', queryset=PurchaseOrderLine.objects.select_related('product'))
                ).get(
                    tenant_id=tenant_id, id=order_id
                )
            except PurchaseOrder.DoesNotExist:
                raise NotFoundError("PurchaseOrder", str(order_id))
        
        order = await asyncio.to_thread(_get)
        return PurchaseOrderWithLinesRead.model_validate(order)

    @staticmethod
    async def get_purchase_summary(tenant_id: str) -> PurchaseSummary:
        """Get summarized purchase metrics for dashboard"""
        def _summary():
            stats = PurchaseOrder.objects.filter(tenant_id=tenant_id).aggregate(
                total_count=Count('id'),
                total_amount=Sum('amount_total'),
                avg_val=Avg('amount_total')
            )
            
            billed_count = PurchaseOrder.objects.filter(
                tenant_id=tenant_id, 
                invoice_status='invoiced'
            ).count()
            
            total_count = stats['total_count'] or 0
            
            return PurchaseSummary(
                total_count=total_count,
                total_amount=float(stats['total_amount'] or 0),
                average_order_value=float(stats['avg_val'] or 0),
                billed_percentage=(billed_count / total_count * 100) if total_count > 0 else 0
            )
            
        return await asyncio.to_thread(_summary)
