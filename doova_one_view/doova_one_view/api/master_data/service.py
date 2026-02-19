"""
Master Data API service
"""

import asyncio
from typing import List, Optional, Tuple
from odoo_app.models.product import Product
from odoo_app.models.partner import Partner
from odoo_app.models.currency import Currency
from doova_one_view.api.master_data.schemas import ProductRead, PartnerRead, CurrencyRead, PaginatedResponse

class MasterDataService:
    """Service for master data dimensions"""
    
    @staticmethod
    async def list_products(
        tenant_id: str,
        limit: int = 50,
        offset: int = 0,
        search: Optional[str] = None
    ) -> PaginatedResponse[ProductRead]:
        """List products for a tenant"""
        def _list():
            qs = Product.objects.filter(tenant_id=tenant_id)
            if search:
                qs = qs.filter(name__icontains=search) | qs.filter(default_code__icontains=search)
            
            total = qs.count()
            items = list(qs[offset:offset+limit])
            return items, total
        
        products, total = await asyncio.to_thread(_list)
        return PaginatedResponse(
            items=[ProductRead.model_validate(p) for p in products],
            total=total,
            limit=limit,
            offset=offset
        )
    
    @staticmethod
    async def list_partners(
        tenant_id: str,
        limit: int = 50,
        offset: int = 0,
        is_customer: Optional[bool] = None,
        is_supplier: Optional[bool] = None,
        search: Optional[str] = None
    ) -> PaginatedResponse[PartnerRead]:
        """List partners for a tenant"""
        def _list():
            qs = Partner.objects.filter(tenant_id=tenant_id)
            if is_customer is not None:
                qs = qs.filter(is_customer=is_customer)
            if is_supplier is not None:
                qs = qs.filter(is_supplier=is_supplier)
            if search:
                qs = qs.filter(name__icontains=search) | qs.filter(email__icontains=search)
            
            total = qs.count()
            items = list(qs[offset:offset+limit])
            return items, total
        
        partners, total = await asyncio.to_thread(_list)
        return PaginatedResponse(
            items=[PartnerRead.model_validate(p) for p in partners],
            total=total,
            limit=limit,
            offset=offset
        )

    @staticmethod
    async def list_currencies(
        tenant_id: str,
        limit: int = 50,
        offset: int = 0,
        active_only: bool = True
    ) -> PaginatedResponse[CurrencyRead]:
        """List currencies for a tenant"""
        def _list():
            qs = Currency.objects.filter(tenant_id=tenant_id)
            if active_only:
                qs = qs.filter(is_active=True)
            
            total = qs.count()
            items = list(qs[offset:offset+limit])
            return items, total
        
        currencies, total = await asyncio.to_thread(_list)
        return PaginatedResponse(
            items=[CurrencyRead.model_validate(c) for c in currencies],
            total=total,
            limit=limit,
            offset=offset
        )
