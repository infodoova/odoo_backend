"""
Inventory API service
"""

import asyncio
from typing import List, Optional
from django.db.models import Sum, Count
from django.utils import timezone
from datetime import timedelta
from odoo_app.models.stock_quant import StockQuant
from odoo_app.models.stock_move import StockMove
from doova_one_view.api.inventory.schemas import (
    StockQuantRead, StockMoveRead, InventorySummary, PaginatedResponse
)

class InventoryService:
    """Service for inventory operations"""
    
    @staticmethod
    async def list_quants(
        tenant_id: str,
        limit: int = 50,
        offset: int = 0,
        product_id: Optional[int] = None
    ) -> PaginatedResponse[StockQuantRead]:
        """List stock quants for a tenant"""
        def _list():
            qs = StockQuant.objects.filter(tenant_id=tenant_id)
            if product_id:
                qs = qs.filter(product_id=product_id)
            
            total = qs.count()
            qs = qs.select_related('product', 'lot')
            qs = qs.order_by('-quantity')
            items = list(qs[offset:offset+limit])
            return items, total
        
        quants, total = await asyncio.to_thread(_list)
        return PaginatedResponse(
            items=[StockQuantRead.model_validate(q) for q in quants],
            total=total,
            limit=limit,
            offset=offset
        )
    
    @staticmethod
    async def list_moves(
        tenant_id: str,
        limit: int = 50,
        offset: int = 0
    ) -> PaginatedResponse[StockMoveRead]:
        """List stock moves for a tenant"""
        def _list():
            qs = StockMove.objects.filter(tenant_id=tenant_id)
            total = qs.count()
            qs = qs.select_related('product')
            qs = qs.order_by('-date')
            items = list(qs[offset:offset+limit])
            return items, total
        
        moves, total = await asyncio.to_thread(_list)
        return PaginatedResponse(
            items=[StockMoveRead.model_validate(m) for m in moves],
            total=total,
            limit=limit,
            offset=offset
        )

    @staticmethod
    async def get_inventory_summary(tenant_id: str) -> InventorySummary:
        """Get summarized inventory metrics"""
        def _summary():
            stats = StockQuant.objects.filter(tenant_id=tenant_id).aggregate(
                total_qty=Sum('quantity'),
                total_reserved=Sum('reserved_quantity'),
                product_count=Count('product_id', distinct=True)
            )
            
            # Count moves in the last 7 days
            seven_days_ago = timezone.now() - timedelta(days=7)
            recent_moves = StockMove.objects.filter(
                tenant_id=tenant_id,
                date__gte=seven_days_ago
            ).count()
            
            return InventorySummary(
                total_products_in_stock=stats['product_count'] or 0,
                total_quantity=float(stats['total_qty'] or 0),
                total_reserved_quantity=float(stats['total_reserved'] or 0),
                recent_moves_count=recent_moves
            )
            
        return await asyncio.to_thread(_summary)
