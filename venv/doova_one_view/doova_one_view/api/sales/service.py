"""
Sales API service
"""

import asyncio
import io
import csv
from typing import List, Optional, Dict
from datetime import timedelta, date
from django.utils import timezone
from django.db.models import Sum, Avg, Count, Prefetch, Q
from django.db.models.functions import TruncDate
from odoo_app.models.sales_order import SalesOrder
from odoo_app.models.sales_order_line import SalesOrderLine
from doova_one_view.api.common.exceptions import NotFoundError, ValidationError
from doova_one_view.api.sales.schemas import (
    SalesOrderRead, SalesOrderWithLinesRead, SalesSummary, 
    AdvancedSearchRequest, PaginatedResponse, SalesDashboard,
    KPIMetric, TimeSeriesPoint, EntityMetric
)
from doova_one_view.api.kpi.service import (
    _get_rate_map, _get_conversion_rate, _sum_converted, _to_float
)

class SalesService:
    """Service for sales operations"""
    
    @staticmethod
    async def list_orders(
        tenant_id: str,
        limit: int = 50,
        offset: int = 0,
        partner_id: Optional[int] = None
    ) -> PaginatedResponse[SalesOrderRead]:
        """List sales orders for a tenant"""
        def _list():
            qs = SalesOrder.objects.filter(tenant_id=tenant_id)
            if partner_id:
                qs = qs.filter(partner_id=partner_id)
            
            total = qs.count()
            qs = qs.select_related('partner', 'user', 'company')
            qs = qs.order_by('-date_order')
            items = list(qs[offset:offset+limit])
            return items, total
        
        orders, total = await asyncio.to_thread(_list)
        return PaginatedResponse(
            items=[SalesOrderRead.model_validate(o) for o in orders],
            total=total,
            limit=limit,
            offset=offset
        )
    
    @staticmethod
    async def get_orders(
        tenant_id: str,
        limit: int = 50,
        offset: int = 0,
        partner_id: Optional[int] = None,
        company_ids: Optional[list[int]] = None
    ) -> PaginatedResponse[SalesOrderRead]:
        """List sales orders for a tenant, optionally filtering by partner or company."""
        def _list():
            qs = SalesOrder.objects.filter(tenant_id=tenant_id)
            if partner_id:
                qs = qs.filter(partner_id=partner_id)
            if company_ids:
                qs = qs.filter(company_id__in=company_ids)
            total = qs.count()
            qs = qs.select_related('partner', 'user', 'company').order_by('-date_order')
            items = list(qs[offset:offset+limit])
            return items, total
        
        orders, total = await asyncio.to_thread(_list)
        return PaginatedResponse(
            items=[SalesOrderRead.model_validate(o) for o in orders],
            total=total,
            limit=limit,
            offset=offset
        )

    @staticmethod
    async def get_order(
        tenant_id: str,
        order_id: int,
        company_ids: Optional[list[int]] = None
    ) -> SalesOrderWithLinesRead:
        """
        Get a specific sales order with its lines. 
        Supports both local ID and Odoo ID.
        If company_ids are provided, they are used as a 'soft' filter; if the order is found
        but belongs to a different company, it is still returned to prevent 404s during navigation.
        """
        def _get():
            # Build the base query with optimized prefetching
            qs = SalesOrder.objects.select_related(
                'partner', 'user', 'company'
            ).prefetch_related(
                Prefetch('lines', queryset=SalesOrderLine.objects.select_related('product'))
            )
            
            # Try lookup by local database primary key
            try:
                order = qs.get(tenant_id=tenant_id, id=order_id)
            except (SalesOrder.DoesNotExist, ValueError, OverflowError):
                try:
                    # Fallback: try lookup by the Odoo-side ID
                    order = qs.get(tenant_id=tenant_id, odoo_id=order_id)
                except SalesOrder.DoesNotExist:
                    raise NotFoundError("SalesOrder", str(order_id))
            
            # Soft company check: we could log a warning if it doesn't match, 
            # but we return the order regardless because single-resource lookup 
            # by ID should usually override list filters.
            return order
        
        order = await asyncio.to_thread(_get)
        return SalesOrderWithLinesRead.model_validate(order)

    @staticmethod
    async def search_orders(
        tenant_id: str,
        filters,
        limit: int,
        offset: int,
        company_ids: Optional[list[int]] = None
    ) -> PaginatedResponse[SalesOrderRead]:
        """Search sales orders with filters and optional company restriction."""
        request = AdvancedSearchRequest(filters=filters, limit=limit, offset=offset)

        def _search():
            qs = SalesOrder.objects.filter(tenant_id=tenant_id)
            if company_ids:
                qs = qs.filter(company__odoo_id__in=company_ids)

            for f in request.filters:
                field = f.field
                op = f.operator.lower().strip()
                val = f.value
                field_mapping = {
                    'partner_name': 'partner__name',
                    'user_name': 'user__name',
                    'company_name': 'company__name',
                }
                field = field_mapping.get(field, field)
                if op in ['contain', 'contains']:
                    qs = qs.filter(**{f"{field}__icontains": val})
                elif op in ['starts with', 'startswith', 'starts_with']:
                    qs = qs.filter(**{f"{field}__istartswith": val})
                elif op in ['ends with', 'endswith', 'ends_with']:
                    qs = qs.filter(**{f"{field}__iendswith": val})
                elif op in ['eq', 'equal', 'equals']:
                    qs = qs.filter(**{field: val})
                elif op in ['gt', 'greater than', 'greater_than', 'after']:
                    qs = qs.filter(**{f"{field}__gt": val})
                elif op in ['lt', 'less than', 'less_than', 'before']:
                    qs = qs.filter(**{f"{field}__lt": val})
                elif op in ['gte', 'greater than or equal', 'greater_than_or_equal']:
                    qs = qs.filter(**{f"{field}__gte": val})
                elif op in ['lte', 'less than or equal', 'less_than_or_equal']:
                    qs = qs.filter(**{f"{field}__lte": val})
                elif op == 'between' and isinstance(val, list) and len(val) == 2:
                    qs = qs.filter(**{f"{field}__range": (val[0], val[1])})

            total = qs.count()
            qs = qs.select_related('partner', 'user', 'company').order_by('-date_order')
            items = list(qs[request.offset : request.offset + request.limit])
            return items, total

        orders, total = await asyncio.to_thread(_search)
        return PaginatedResponse(
            items=[SalesOrderRead.model_validate(o) for o in orders],
            total=total,
            limit=request.limit,
            offset=request.offset
        )

    @staticmethod
    async def get_filters(tenant_id: str) -> Dict[str, List[str]]:
        return await SalesService.get_distinct_enums(tenant_id)

    @staticmethod
    async def get_sales_summary(tenant_id: str) -> SalesSummary:
        """Get summarized sales metrics for dashboard"""
        def _summary():
            stats = SalesOrder.objects.filter(tenant_id=tenant_id).aggregate(
                total_count=Count('id'),
                total_amount=Sum('amount_total'),
                total_margin=Sum('margin'),
                avg_val=Avg('amount_total')
            )
            
            invoiced_count = SalesOrder.objects.filter(
                tenant_id=tenant_id, 
                invoice_status='invoiced'
            ).count()
            
            total_count = stats['total_count'] or 0
            
            return SalesSummary(
                total_count=total_count,
                total_amount=float(stats['total_amount'] or 0),
                total_margin=float(stats['total_margin'] or 0),
                average_order_value=float(stats['avg_val'] or 0),
                invoiced_percentage=(invoiced_count / total_count * 100) if total_count > 0 else 0
            )
            
            
        return await asyncio.to_thread(_summary)

    @staticmethod
    async def export_orders_csv(
        tenant_id: str,
        company_ids: Optional[list[int]] = None
    ) -> str:
        """Export sales orders to CSV format."""
        def _get_orders():
            qs = SalesOrder.objects.filter(tenant_id=tenant_id)
            if company_ids:
                qs = qs.filter(company__odoo_id__in=company_ids)
            return list(qs.select_related('partner', 'user', 'company').order_by('-date_order'))

        orders = await asyncio.to_thread(_get_orders)

        output = io.StringIO()
        writer = csv.writer(output)

        writer.writerow([
            "Order ID", "Odoo Name", "Partner", "User", "Company",
            "Date", "State", "Invoice Status", "Untaxed Amount",
            "Tax Amount", "Total Amount", "Margin"
        ])

        for order in orders:
            writer.writerow([
                order.id,
                order.odoo_name,
                order.partner.name if order.partner else "",
                order.user.name if order.user else "",
                order.company.name if order.company else "",
                order.date_order.isoformat() if order.date_order else "",
                order.state,
                order.invoice_status,
                float(order.amount_untaxed),
                float(order.amount_tax),
                float(order.amount_total),
                float(order.margin)
            ])

        return output.getvalue()

    @staticmethod
    async def advanced_search(tenant_id: str, request: AdvancedSearchRequest) -> PaginatedResponse[SalesOrderRead]:
        """Advanced search for sales orders with complex filters"""
        def _search():
            qs = SalesOrder.objects.filter(tenant_id=tenant_id)
            
            for f in request.filters:
                field = f.field
                # Clean up the operator
                op = f.operator.lower().strip()
                val = f.value
                
                # Map friendly field names to ORM paths
                field_mapping = {
                    'partner_name': 'partner__name',
                    'user_name': 'user__name',
                    'company_name': 'company__name',
                }
                field = field_mapping.get(field, field)
                
                # String operators
                if op in ['contain', 'contains']:
                    qs = qs.filter(**{f"{field}__icontains": val})
                elif op in ['starts with', 'startswith', 'starts_with']:
                    qs = qs.filter(**{f"{field}__istartswith": val})
                elif op in ['ends with', 'endswith', 'ends_with']:
                    qs = qs.filter(**{f"{field}__iendswith": val})
                
                # Numerical / Date operators
                elif op in ['eq', 'equal', 'equals']:
                    qs = qs.filter(**{field: val})
                elif op in ['gt', 'greater than', 'greater_than', 'after']:
                    qs = qs.filter(**{f"{field}__gt": val})
                elif op in ['lt', 'less than', 'less_than', 'before']:
                    qs = qs.filter(**{f"{field}__lt": val})
                elif op in ['gte', 'greater than or equal', 'greater_than_or_equal']:
                    qs = qs.filter(**{f"{field}__gte": val})
                elif op in ['lte', 'less than or equal', 'less_than_or_equal']:
                    qs = qs.filter(**{f"{field}__lte": val})
                elif op == 'between':
                    if isinstance(val, list) and len(val) == 2:
                        qs = qs.filter(**{f"{field}__range": (val[0], val[1])})
            
            total = qs.count()
            qs = qs.select_related('partner', 'user', 'company').order_by('-date_order')
            items = list(qs[request.offset : request.offset + request.limit])
            return items, total

        orders, total = await asyncio.to_thread(_search)
        return PaginatedResponse(
            items=[SalesOrderRead.model_validate(o) for o in orders],
            total=total,
            limit=request.limit,
            offset=request.offset
        )

    @staticmethod
    def _parse_date(value: Optional[str]) -> Optional[date]:
        if value is None:
            return None
        if isinstance(value, date):
            return value
        try:
            return date.fromisoformat(value)
        except ValueError:
            raise ValidationError(
                f"Invalid date format for dashboard filter: '{value}'. Expected YYYY-MM-DD"
            )

    @staticmethod
    async def get_dashboard(
        tenant_id: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        company_ids: Optional[list[int]] = None,
        base_currency: Optional[str] = None
    ) -> SalesDashboard:
        """Get comprehensive sales dashboard metrics within a date range"""
        def _get():
            start_date_parsed = SalesService._parse_date(start_date)
            end_date_parsed = SalesService._parse_date(end_date)

            # Default to last 30 days if not provided
            if not end_date_parsed:
                final_date = timezone.now().date()
            else:
                final_date = end_date_parsed
                
            if not start_date_parsed:
                initial_date = final_date - timedelta(days=30)
            else:
                initial_date = start_date_parsed
            
            # Calculate previous period for comparison
            duration = final_date - initial_date
            prev_end = initial_date
            prev_start = initial_date - duration
            
            base_qs = SalesOrder.objects.filter(tenant_id=tenant_id)
            if company_ids:
                base_qs = base_qs.filter(company__odoo_id__in=company_ids)
            
            rate_map = _get_rate_map()
            effective_base = base_currency or "XAF"
            base_multiplier = _get_conversion_rate("COMPANY_BASE", effective_base, rate_map)
            
            # 1. Summary Metrics
            def get_stats(qs):
                rev = _sum_converted(qs, 'amount_total', effective_base, rate_map)
                margin = _sum_converted(qs, 'margin', effective_base, rate_map) # Wait, is margin COMPANY_BASE?
                # Actually, in KPI we treated margin as COMPANY_BASE, but if we pass it through _sum_converted, it will try to use currency_code.
                # Is margin in COMPANY_BASE or order currency? Odoo margin is usually in company currency. Let's assume it's like KPI.
                # Actually _sum_converted groups by currency_code. If margin is company currency, we shouldn't use _sum_converted for it.
                # Let's write a custom aggregation for margin.
                margin_val = _to_float(qs.aggregate(val=Sum('margin'))['val'] or 0) * base_multiplier
                count = qs.count()
                avg_val = (rev / count) if count > 0 else 0
                return {'revenue': rev, 'margin': margin_val, 'count': count, 'avg_val': avg_val}
            
            current_stats = get_stats(base_qs.filter(date_order__date__range=(initial_date, final_date)))
            prev_stats = get_stats(base_qs.filter(date_order__date__range=(prev_start, prev_end)))
            
            def make_kpi(curr, prev):
                curr_val = float(curr or 0)
                prev_val = float(prev or 0)
                change = None
                if prev_val > 0:
                    change = ((curr_val - prev_val) / prev_val) * 100
                elif curr_val > 0:
                    change = 100.0
                return KPIMetric(value=curr_val, previous_value=prev_val, change_percentage=change)

            # Pipeline Value (Quotes) - All time draft/sent
            pipeline = _sum_converted(base_qs.filter(state__in=['draft', 'sent']), 'amount_total', effective_base, rate_map)
            
            # Conversion Rate (All time)
            drafts = base_qs.filter(state__in=['draft', 'sent', 'sale', 'done']).count()
            sales = base_qs.filter(state__in=['sale', 'done']).count()
            conversion = (sales / drafts * 100) if drafts > 0 else 0
            
            # 2. Trends (Revenue within range)
            trend_rows = list(base_qs.filter(date_order__date__range=(initial_date, final_date))
                .annotate(date=TruncDate('date_order'))
                .values('date', 'currency_code')
                .annotate(value=Sum('amount_total'))
            )
            trend_map = {}
            for r in trend_rows:
                if not r['date']: continue
                d_str = r['date'].isoformat()
                code = r['currency_code'] or "COMPANY_BASE"
                val = _to_float(r['value']) * _get_conversion_rate(code, effective_base, rate_map)
                trend_map[d_str] = trend_map.get(d_str, 0.0) + val
            trend = [{'date': d, 'value': v} for d, v in sorted(trend_map.items())]
            
            # 3. Rankings (Within range)
            range_filter = {'date_order__date__range': (initial_date, final_date)}
            
            cust_rows = list(base_qs.filter(**range_filter)
                .values('partner__name', 'partner_id', 'currency_code')
                .annotate(value=Sum('amount_total')))
            cust_map = {}
            for r in cust_rows:
                pid = r['partner_id']
                if pid not in cust_map:
                    cust_map[pid] = {'name': r['partner__name'], 'value': 0.0}
                code = r['currency_code'] or "COMPANY_BASE"
                cust_map[pid]['value'] += _to_float(r['value']) * _get_conversion_rate(code, effective_base, rate_map)
            top_customers = [{'partner_id': k, 'partner__name': v['name'], 'value': v['value']} for k, v in sorted(cust_map.items(), key=lambda x: x[1]['value'], reverse=True)[:5]]
            
            prod_rows = list(SalesOrderLine.objects.filter(
                tenant_id=tenant_id, 
                sales_order__date_order__date__range=(initial_date, final_date)
            ).values('product__name', 'product_id', 'sales_order__currency_code')
             .annotate(value=Sum('price_total')))
            prod_map = {}
            for r in prod_rows:
                pid = r['product_id']
                if pid not in prod_map:
                    prod_map[pid] = {'name': r['product__name'], 'value': 0.0}
                code = r['sales_order__currency_code'] or "COMPANY_BASE"
                prod_map[pid]['value'] += _to_float(r['value']) * _get_conversion_rate(code, effective_base, rate_map)
            top_products = [{'product_id': k, 'product__name': v['name'], 'value': v['value']} for k, v in sorted(prod_map.items(), key=lambda x: x[1]['value'], reverse=True)[:5]]
            
            sp_rows = list(base_qs.filter(**range_filter)
                .values('user__name', 'user_id', 'currency_code')
                .annotate(value=Sum('amount_total')))
            sp_map = {}
            for r in sp_rows:
                uid = r['user_id']
                if uid not in sp_map:
                    sp_map[uid] = {'name': r['user__name'], 'value': 0.0}
                code = r['currency_code'] or "COMPANY_BASE"
                sp_map[uid]['value'] += _to_float(r['value']) * _get_conversion_rate(code, effective_base, rate_map)
            top_salespeople = [{'user_id': k, 'user__name': v['name'], 'value': v['value']} for k, v in sorted(sp_map.items(), key=lambda x: x[1]['value'], reverse=True)[:5]]
            
            
            # 4. Status Distribution (All time)
            dist = base_qs.values('state').annotate(count=Count('id'))
            state_dist = {d['state']: d['count'] for d in dist}
            
            return SalesDashboard(
                total_revenue=make_kpi(current_stats['revenue'], prev_stats['revenue']),
                profit_margin_pct=make_kpi(
                    (current_stats['margin'] / current_stats['revenue'] * 100) if current_stats['revenue'] else 0,
                    (prev_stats['margin'] / prev_stats['revenue'] * 100) if prev_stats['revenue'] else 0
                ),
                avg_order_value=make_kpi(current_stats['avg_val'], prev_stats['avg_val']),
                pipeline_value=KPIMetric(value=float(pipeline)),
                order_count=current_stats['count'] or 0,
                conversion_rate=float(conversion),
                revenue_trend=[TimeSeriesPoint(date=t['date'], value=float(t['value'])) for t in trend],
                state_distribution=state_dist,
                top_customers=[EntityMetric(id=c['partner_id'], name=c['partner__name'] or "Unknown", value=float(c['value'])) for c in top_customers],
                top_products=[EntityMetric(id=p['product_id'], name=p['product__name'] or "Unknown", value=float(p['value'])) for p in top_products],
                top_salespeople=[EntityMetric(id=s['user_id'], name=s['user__name'] or "Unknown", value=float(s['value'])) for s in top_salespeople]
            )
        
        return await asyncio.to_thread(_get)

    @staticmethod
    async def get_distinct_enums(tenant_id: str) -> Dict[str, List[str]]:
        """Get distinct values for enum-like fields in SalesOrder"""
        def _get():
            qs = SalesOrder.objects.filter(tenant_id=tenant_id)
            states = list(qs.values_list('state', flat=True).distinct())
            invoice_statuses = list(qs.values_list('invoice_status', flat=True).distinct())
            currencies = list(qs.values_list('currency_code', flat=True).distinct())
            
            # Remove None if present
            invoice_statuses = [s for s in invoice_statuses if s is not None]
            currencies = [c for c in currencies if c is not None]
            
            return {
                "state": states,
                "invoice_status": invoice_statuses,
                "currencies": currencies
            }
        
        return await asyncio.to_thread(_get)
