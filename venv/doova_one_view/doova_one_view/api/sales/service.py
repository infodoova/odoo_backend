"""
Sales API service
"""

import asyncio
import io
import csv
from typing import List, Optional, Dict
from datetime import timedelta, date, datetime, time
from django.utils import timezone
from django.db.models import Sum, Avg, Count, Prefetch, Q
from django.db.models.functions import TruncDate
from odoo_app.models.sales_order import SalesOrder
from odoo_app.models.sales_order_line import SalesOrderLine
from doova_one_view.api.common.exceptions import NotFoundError, ValidationError
from doova_one_view.api.sales.schemas import (
    SalesOrderRead, SalesOrderWithLinesRead, SalesSummary, 
    AdvancedSearchRequest, PaginatedResponse, SalesDashboard,
    KPIMetric, TimeSeriesPoint, EntityMetric,
    MetricDetailResponse, MetricDetailCompanyGroup, MetricDetailOrder,
    DailyOrdersResponse, MarketBreakdownResponse,
    EntityProfileResponse, ProductSaleLineDetail, ProductSalesDetailResponse,
    CustomerMetric, CustomerMetricsResponse
)
from odoo_app.models.partner import Partner
from odoo_app.models.odoo_user import User as OdooUser
from odoo_app.models.product import Product
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

        def _clean_date_val(v):
            if v is None:
                return None
            if isinstance(v, (datetime, date)):
                return v.strftime("%Y-%m-%d")
            s = str(v).strip()
            if not s:
                return None
            if len(s) >= 10 and s[4] == '-' and s[7] == '-':
                return s[:10]
            return s

        def _search():
            qs = SalesOrder.objects.filter(tenant_id=tenant_id)
            if company_ids:
                qs = qs.filter(company_id__in=company_ids)

            field_map = {
                "id": "id",
                "odoo_id": "odoo_id",
                "odoo_name": "odoo_name",
                "name": "odoo_name",
                "partner_name": "partner__name",
                "customer_name": "partner__name",
                "customer": "partner__name",
                "partner_id": "partner_id",
                "partner": "partner__name",
                "user_name": "user__name",
                "salesperson_name": "user__name",
                "salesperson": "user__name",
                "user_id": "user_id",
                "user": "user__name",
                "company_name": "company__name",
                "company": "company__name",
                "company_id": "company_id",
                "date": "date_order",
                "date_order": "date_order",
                "order_date": "date_order",
                "validity_date": "validity_date",
                "commitment_date": "commitment_date",
                "state": "state",
                "invoice_status": "invoice_status",
                "amount_untaxed": "amount_untaxed",
                "amount_tax": "amount_tax",
                "amount_total": "amount_total",
                "margin": "margin",
                "currency_code": "currency_code",
                "synced_at": "synced_at",
                "odoo_create_date": "odoo_create_date",
                "odoo_write_date": "odoo_write_date",
            }

            DATE_FIELDS = {
                "date_order",
                "validity_date",
                "commitment_date",
                "synced_at",
                "odoo_create_date",
                "odoo_write_date",
            }

            for f in request.filters:
                raw_field = getattr(f, "field", None) or (f.get("field") if isinstance(f, dict) else None)
                if not raw_field:
                    continue
                raw_field = str(raw_field).strip()
                op = (getattr(f, "operator", None) or (f.get("operator") if isinstance(f, dict) else "")).lower().strip()
                val = getattr(f, "value", None) if hasattr(f, "value") else (f.get("value") if isinstance(f, dict) else None)
                max_val = (
                    getattr(f, "max_value", None)
                    or getattr(f, "maxValue", None)
                    or (f.get("max_value") if isinstance(f, dict) else None)
                    or (f.get("maxValue") if isinstance(f, dict) else None)
                )

                orm_field = field_map.get(raw_field, raw_field)
                is_date = orm_field in DATE_FIELDS

                if is_date:
                    if op in ["contain", "contains", "startswith", "starts with", "starts_with", "endswith", "ends with", "ends_with"]:
                        clean_v = _clean_date_val(val)
                        if clean_v:
                            qs = qs.filter(**{f"{orm_field}__date__icontains": clean_v})
                    elif op in ["eq", "equal", "equals", "=", "exact", "is"]:
                        clean_v = _clean_date_val(val)
                        if clean_v:
                            qs = qs.extra(
                                where=[f"({orm_field})::date = CAST(%s AS date)"],
                                params=[str(clean_v)]
                            )
                    elif op in ["gt", "greater than", "greater_than", "after"]:
                        clean_v = _clean_date_val(val)
                        if clean_v:
                            qs = qs.extra(
                                where=[f"({orm_field})::date > CAST(%s AS date)"],
                                params=[str(clean_v)]
                            )
                    elif op in ["gte", "greater than or equal", "greater_than_or_equal"]:
                        clean_v = _clean_date_val(val)
                        if clean_v:
                            qs = qs.extra(
                                where=[f"({orm_field})::date >= CAST(%s AS date)"],
                                params=[str(clean_v)]
                            )
                    elif op in ["lt", "less than", "less_than", "before"]:
                        clean_v = _clean_date_val(val)
                        if clean_v:
                            qs = qs.extra(
                                where=[f"({orm_field})::date < CAST(%s AS date)"],
                                params=[str(clean_v)]
                            )
                    elif op in ["lte", "less than or equal", "less_than_or_equal"]:
                        clean_v = _clean_date_val(val)
                        if clean_v:
                            qs = qs.extra(
                                where=[f"({orm_field})::date <= CAST(%s AS date)"],
                                params=[str(clean_v)]
                            )
                    elif op == "between":
                        v1 = None
                        v2 = None
                        if max_val is not None and str(max_val).strip() != "":
                            v1 = _clean_date_val(val)
                            v2 = _clean_date_val(max_val)
                        elif isinstance(val, (list, tuple)) and len(val) >= 2:
                            v1 = _clean_date_val(val[0])
                            v2 = _clean_date_val(val[1])
                        elif isinstance(val, str) and ("," in val or " to " in val or " - " in val):
                            parts = [p.strip() for p in val.replace(" to ", ",").replace(" - ", ",").split(",") if p.strip()]
                            if len(parts) >= 2:
                                v1 = _clean_date_val(parts[0])
                                v2 = _clean_date_val(parts[1])
                            elif len(parts) == 1:
                                v1 = _clean_date_val(parts[0])
                        else:
                            v1 = _clean_date_val(val)

                        if v1 and v2:
                            qs = qs.extra(
                                where=[f"({orm_field})::date BETWEEN CAST(%s AS date) AND CAST(%s AS date)"],
                                params=[str(v1), str(v2)]
                            )
                        elif v1:
                            qs = qs.extra(
                                where=[f"({orm_field})::date >= CAST(%s AS date)"],
                                params=[str(v1)]
                            )
                        elif v2:
                            qs = qs.extra(
                                where=[f"({orm_field})::date <= CAST(%s AS date)"],
                                params=[str(v2)]
                            )
                    elif op in ["in"]:
                        if isinstance(val, (list, tuple, set)):
                            clean_list = [_clean_date_val(x) for x in val if _clean_date_val(x)]
                            if clean_list:
                                qs = qs.filter(**{f"{orm_field}__date__in": clean_list})
                else:
                    # Non-date fields
                    if op in ['contain', 'contains']:
                        if val is not None and str(val).strip() != "":
                            qs = qs.filter(**{f"{orm_field}__icontains": val})
                    elif op in ['starts with', 'startswith', 'starts_with']:
                        if val is not None and str(val).strip() != "":
                            qs = qs.filter(**{f"{orm_field}__istartswith": val})
                    elif op in ['ends with', 'endswith', 'ends_with']:
                        if val is not None and str(val).strip() != "":
                            qs = qs.filter(**{f"{orm_field}__iendswith": val})
                    elif op in ['eq', 'equal', 'equals', '=', 'exact', 'is']:
                        if val is not None:
                            qs = qs.filter(**{orm_field: val})
                    elif op in ['gt', 'greater than', 'greater_than', 'after']:
                        if val is not None:
                            qs = qs.filter(**{f"{orm_field}__gt": val})
                    elif op in ['lt', 'less than', 'less_than', 'before']:
                        if val is not None:
                            qs = qs.filter(**{f"{orm_field}__lt": val})
                    elif op in ['gte', 'greater than or equal', 'greater_than_or_equal']:
                        if val is not None:
                            qs = qs.filter(**{f"{orm_field}__gte": val})
                    elif op in ['lte', 'less than or equal', 'less_than_or_equal']:
                        if val is not None:
                            qs = qs.filter(**{f"{orm_field}__lte": val})
                    elif op == 'between':
                        if max_val is not None and str(max_val).strip() != "":
                            qs = qs.filter(**{f"{orm_field}__range": (val, max_val)})
                        elif isinstance(val, (list, tuple)) and len(val) == 2:
                            qs = qs.filter(**{f"{orm_field}__range": (val[0], val[1])})
                        elif val is not None:
                            qs = qs.filter(**{f"{orm_field}__gte": val})
                    elif op in ['in']:
                        if isinstance(val, (list, tuple, set)):
                            qs = qs.filter(**{f"{orm_field}__in": val})

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
                qs = qs.filter(company_id__in=company_ids)
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
        return await SalesService.search_orders(
            tenant_id=tenant_id,
            filters=request.filters,
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
    def _apply_date_filter(qs, start_date=None, end_date=None, date_column="date_order"):
        """
        Apply strict date filtering without timezone conversion:
        (date_column)::date BETWEEN CAST(%s AS date) AND CAST(%s AS date)
        """
        s_date = SalesService._parse_date(start_date)
        e_date = SalesService._parse_date(end_date)
        if s_date and e_date:
            return qs.extra(
                where=[f"({date_column})::date BETWEEN CAST(%s AS date) AND CAST(%s AS date)"],
                params=[str(s_date), str(e_date)]
            )
        elif s_date:
            return qs.extra(
                where=[f"({date_column})::date >= CAST(%s AS date)"],
                params=[str(s_date)]
            )
        elif e_date:
            return qs.extra(
                where=[f"({date_column})::date <= CAST(%s AS date)"],
                params=[str(e_date)]
            )
        return qs

    @staticmethod
    def _apply_day_filter(qs, day, date_column="date_order"):
        """
        Apply single calendar day filter: (date_column)::date = CAST(%s AS date)
        """
        d_date = SalesService._parse_date(day)
        if not d_date:
            raise ValidationError(f"Invalid date format: '{day}'. Expected YYYY-MM-DD")
        return qs.extra(
            where=[f"({date_column})::date = CAST(%s AS date)"],
            params=[str(d_date)]
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
                base_qs = base_qs.filter(company_id__in=company_ids)
            
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
            
            confirmed_qs = base_qs.filter(state__in=['sale', 'done'])
            confirmed_range_qs = SalesService._apply_date_filter(confirmed_qs, initial_date, final_date)
            current_stats = get_stats(confirmed_range_qs)
            prev_stats = get_stats(SalesService._apply_date_filter(confirmed_qs, prev_start, prev_end))
            
            def make_kpi(curr, prev):
                curr_val = float(curr or 0)
                prev_val = float(prev or 0)
                change = None
                if prev_val > 0:
                    change = ((curr_val - prev_val) / prev_val) * 100
                elif curr_val > 0:
                    change = 100.0
                return KPIMetric(value=curr_val, previous_value=prev_val, change_percentage=change)

            # Pipeline Value (Quotes) - open quotations (draft/sent) whose order date falls
            # inside the selected period.
            pipeline_qs = SalesService._apply_date_filter(
                base_qs.filter(state__in=['draft', 'sent']), initial_date, final_date
            )
            pipeline = _sum_converted(pipeline_qs, 'amount_total', effective_base, rate_map)
            
            # Conversion Rate for the selected period: confirmed orders / all non-cancelled
            # quotes and orders whose order date falls inside the same date range as the
            # other dashboard figures.
            period_qs = SalesService._apply_date_filter(
                base_qs.filter(state__in=['draft', 'sent', 'sale', 'done']), initial_date, final_date
            )
            quotes_and_orders = period_qs.count()
            confirmed_orders = period_qs.filter(state__in=['sale', 'done']).count()
            conversion = (confirmed_orders / quotes_and_orders * 100) if quotes_and_orders > 0 else 0
            
            # 2. Trends (Revenue within range)
            trend_rows = list(confirmed_range_qs
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
            cust_rows = list(confirmed_range_qs
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
            
            prod_qs = SalesOrderLine.objects.filter(
                tenant_id=tenant_id, 
                sales_order__state__in=['sale', 'done']
            )
            prod_qs = SalesService._apply_date_filter(
                prod_qs, initial_date, final_date, date_column="fact_sales_orders.date_order"
            )
            prod_rows = list(prod_qs.exclude(product__product_type='service').exclude(product__name__icontains='discount')
            .values('product__name', 'product_id', 'sales_order__currency_code')
             .annotate(value=Sum('price_total')))
            prod_map = {}
            for r in prod_rows:
                pid = r['product_id']
                if pid not in prod_map:
                    prod_map[pid] = {'name': r['product__name'], 'value': 0.0}
                code = r['sales_order__currency_code'] or "COMPANY_BASE"
                prod_map[pid]['value'] += _to_float(r['value']) * _get_conversion_rate(code, effective_base, rate_map)
            top_products = [{'product_id': k, 'product__name': v['name'], 'value': v['value']} for k, v in sorted(prod_map.items(), key=lambda x: x[1]['value'], reverse=True)[:5]]
            
            sp_rows = list(confirmed_range_qs
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
                total_profit=make_kpi(current_stats['margin'], prev_stats['margin']),
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


    @staticmethod
    async def get_dashboard_metric_details(
        tenant_id: str,
        metric: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        company_ids: Optional[list[int]] = None,
        base_currency: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> MetricDetailResponse:
        """Get detailed drill-down data for a specific dashboard metric"""
        def _get():
            start_date_parsed = SalesService._parse_date(start_date)
            end_date_parsed = SalesService._parse_date(end_date)
            
            if not end_date_parsed:
                final_date = timezone.now().date()
            else:
                final_date = end_date_parsed
                
            if not start_date_parsed:
                initial_date = final_date - timedelta(days=30)
            else:
                initial_date = start_date_parsed

            base_qs = SalesOrder.objects.filter(tenant_id=tenant_id)
            if company_ids:
                base_qs = base_qs.filter(company_id__in=company_ids)

            # Apply specific metric filters
            # Use (date_order)::date BETWEEN CAST(%s AS date) AND CAST(%s AS date), consistent
            # with get_dashboard() so both endpoints return matching totals.
            if metric == 'pipeline_value':
                qs = base_qs.filter(state__in=['draft', 'sent'])
            elif metric in ['total_revenue', 'total_profit', 'order_count', 'avg_order_value']:
                qs = SalesService._apply_date_filter(
                    base_qs.filter(state__in=['sale', 'done']),
                    initial_date,
                    final_date
                )
            else:
                raise ValidationError(f"Metric drill-down not supported for: {metric}")

            # Fetch orders with lines and product info to minimize N+1 queries
            orders = qs.select_related('company').prefetch_related(
                'lines', 'lines__product'
            ).order_by('-date_order')

            rate_map = _get_rate_map()
            effective_base = base_currency or "XAF"
            
            groups = {}
            total_metric_sum = 0.0
            flat_orders = []

            for order in orders:
                company_obj = order.company
                cid   = company_obj.odoo_id if company_obj else None
                cname = company_obj.name     if company_obj else "Unknown Company"
                if cid not in groups:
                    groups[cid] = {
                        "company_id": cid,
                        "company_name": cname,
                        "metric_value": 0.0,
                        "order_count": 0
                    }

                code = order.currency_code or "COMPANY_BASE"
                conversion_rate = _get_conversion_rate(code, effective_base, rate_map)
                
                converted_amount = _to_float(order.amount_total) * conversion_rate
                converted_margin = _to_float(order.margin) * conversion_rate

                order_value = 0.0
                if metric in ['total_revenue', 'pipeline_value', 'avg_order_value']:
                    order_value = converted_amount
                elif metric == 'total_profit':
                    order_value = converted_margin
                elif metric == 'order_count':
                    order_value = 1.0

                groups[cid]["metric_value"] += order_value
                total_metric_sum += order_value
                groups[cid]["order_count"] += 1

                flat_orders.append(MetricDetailOrder(
                    id=order.id,
                    odoo_id=order.odoo_id,
                    odoo_name=order.odoo_name,
                    company_id=cid,
                    company_name=cname,
                    customer=order.partner,
                    salesperson=order.user,
                    date_order=order.date_order,
                    state=order.state,
                    amount_total=_to_float(order.amount_total),
                    margin=_to_float(order.margin),
                    currency_code=code,
                    lines=list(order.lines.all()),
                    converted_amount=converted_amount,
                    converted_margin=converted_margin
                ))

            # Average order value requires dividing the sum by count at the group level
            if metric == 'avg_order_value':
                total_count = len(flat_orders)
                total_metric_sum = total_metric_sum / total_count if total_count > 0 else 0.0
                for g in groups.values():
                    g["metric_value"] = g["metric_value"] / g["order_count"] if g["order_count"] > 0 else 0.0

            company_groups = [
                MetricDetailCompanyGroup(
                    company_id=g['company_id'],
                    company_name=g['company_name'],
                    metric_value=g['metric_value']
                ) for g in groups.values()
            ]

            total_items = len(flat_orders)
            paginated_orders = flat_orders[offset:offset+limit]

            return MetricDetailResponse(
                metric_name=metric,
                base_currency=effective_base,
                total_metric_value=total_metric_sum,
                company_groups=company_groups,
                items=paginated_orders,
                total=total_items,
                limit=limit,
                offset=offset
            )
            
        return await asyncio.to_thread(_get)

    @staticmethod
    async def get_daily_orders(
        tenant_id: str,
        day: str,
        company_ids: Optional[list[int]] = None,
        base_currency: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> DailyOrdersResponse:
        """Return all confirmed orders placed on a specific calendar day (Daily Performance drill-down)"""
        def _get():
            target_date = SalesService._parse_date(day)
            if not target_date:
                raise ValidationError("'day' parameter is required in YYYY-MM-DD format")

            # Use (date_order)::date = CAST(%s AS date) for date-only comparison, consistent
            # with get_dashboard()'s TruncDate grouping so totals match.
            base_qs = SalesService._apply_day_filter(
                SalesOrder.objects.filter(
                    tenant_id=tenant_id,
                    state__in=['sale', 'done']
                ),
                target_date
            )
            if company_ids:
                base_qs = base_qs.filter(company_id__in=company_ids)

            orders = base_qs.select_related('company').prefetch_related(
                'lines', 'lines__product'
            ).order_by('date_order')

            effective_base = (base_currency or 'XAF').upper()
            rate_map = _get_rate_map()

            groups: dict[int, dict] = {}
            flat_orders = []
            total_revenue = 0.0

            for order in orders:
                company_obj = order.company
                cid   = company_obj.odoo_id if company_obj else None
                cname = company_obj.name     if company_obj else 'Unknown'

                if cid not in groups:
                    groups[cid] = {'company_id': cid, 'company_name': cname, 'metric_value': 0.0}

                code = order.currency_code or 'COMPANY_BASE'
                rate = _get_conversion_rate(code, effective_base, rate_map)
                converted_amount = _to_float(order.amount_total) * rate

                groups[cid]['metric_value'] += converted_amount
                total_revenue += converted_amount

                flat_orders.append(MetricDetailOrder(
                    id=order.id,
                    odoo_id=order.odoo_id,
                    odoo_name=order.odoo_name,
                    company_id=cid,
                    company_name=cname,
                    customer=order.partner,
                    salesperson=order.user,
                    date_order=order.date_order,
                    state=order.state,
                    amount_total=_to_float(order.amount_total),
                    margin=_to_float(order.margin),
                    currency_code=code,
                    lines=list(order.lines.all()),
                    converted_amount=converted_amount,
                    converted_margin=_to_float(order.margin) * rate
                ))

            company_groups = [
                MetricDetailCompanyGroup(**g) for g in groups.values()
            ]

            total_items = len(flat_orders)
            paginated_orders = flat_orders[offset:offset + limit]

            return DailyOrdersResponse(
                date=target_date.isoformat(),
                base_currency=effective_base,
                total_revenue=total_revenue,
                order_count=total_items,
                company_groups=company_groups,
                items=paginated_orders,
                total=total_items,
                limit=limit,
                offset=offset
            )

        return await asyncio.to_thread(_get)

    @staticmethod
    async def get_market_breakdown_details(
        tenant_id: str,
        section: str,
        entity_id: int,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        company_ids: Optional[list[int]] = None,
        base_currency: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> MarketBreakdownResponse:
        """Drill into a market-breakdown entity: top_customers, top_products, or top_salespeople.
        Returns all confirmed orders linked to the given entity within the date range."""
        SECTION_FILTER = {
            'top_customers':   ('partner_id',           'partner__name'),
            'top_products':    ('lines__product_id',    'lines__product__name'),
            'top_salespeople': ('user_id',              'user__name'),
        }
        if section not in SECTION_FILTER:
            raise ValidationError(
                f"Invalid section '{section}'. Must be one of: {', '.join(SECTION_FILTER)}"
            )

        def _get():
            fk_field, name_field = SECTION_FILTER[section]

            initial_date = SalesService._parse_date(start_date)
            final_date = SalesService._parse_date(end_date)
            if not final_date:
                final_date = timezone.now().date()
            if not initial_date:
                initial_date = final_date - timedelta(days=30)

            base_qs = SalesOrder.objects.filter(
                tenant_id=tenant_id,
                state__in=['sale', 'done']
            )
            base_qs = SalesService._apply_date_filter(base_qs, initial_date, final_date)
            if company_ids:
                base_qs = base_qs.filter(company_id__in=company_ids)

            # Filter by the chosen entity
            base_qs = base_qs.filter(**{fk_field: entity_id})

            # Resolve entity name
            first = base_qs.first()
            if first is None:
                entity_name = 'Unknown'
            else:
                # Navigate the relation to get the name
                if section == 'top_customers':
                    entity_name = first.partner.name if first.partner else 'Unknown'
                elif section == 'top_products':
                    prod = first.lines.filter(product_id=entity_id).first()
                    entity_name = prod.product.name if (prod and prod.product) else 'Unknown'
                else:  # top_salespeople
                    entity_name = first.user.name if first.user else 'Unknown'

            orders = base_qs.select_related('company').prefetch_related(
                'lines', 'lines__product'
            ).distinct().order_by('-date_order')

            effective_base = (base_currency or 'XAF').upper()
            rate_map = _get_rate_map()

            groups: dict[int, dict] = {}
            flat_orders = []
            total_revenue = 0.0

            for order in orders:
                company_obj = order.company
                cid   = company_obj.odoo_id if company_obj else None
                cname = company_obj.name     if company_obj else 'Unknown'

                if cid not in groups:
                    groups[cid] = {'company_id': cid, 'company_name': cname, 'metric_value': 0.0}

                code = order.currency_code or 'COMPANY_BASE'
                rate = _get_conversion_rate(code, effective_base, rate_map)
                converted_amount = _to_float(order.amount_total) * rate

                groups[cid]['metric_value'] += converted_amount
                total_revenue += converted_amount

                flat_orders.append(MetricDetailOrder(
                    id=order.id,
                    odoo_id=order.odoo_id,
                    odoo_name=order.odoo_name,
                    company_id=cid,
                    company_name=cname,
                    customer=order.partner,
                    salesperson=order.user,
                    date_order=order.date_order,
                    state=order.state,
                    amount_total=_to_float(order.amount_total),
                    margin=_to_float(order.margin),
                    currency_code=code,
                    lines=list(order.lines.all()),
                    converted_amount=converted_amount,
                    converted_margin=_to_float(order.margin) * rate
                ))

            company_groups = [
                MetricDetailCompanyGroup(**g) for g in groups.values()
            ]

            total_items = len(flat_orders)
            paginated_orders = flat_orders[offset:offset + limit]

            return MarketBreakdownResponse(
                section=section,
                entity_id=entity_id,
                entity_name=entity_name,
                base_currency=effective_base,
                total_revenue=total_revenue,
                order_count=total_items,
                company_groups=company_groups,
                items=paginated_orders,
                total=total_items,
                limit=limit,
                offset=offset
            )

        return await asyncio.to_thread(_get)

    # ── Entity Profile (Salesperson / Customer) ────────────────────────────

    @staticmethod
    async def get_entity_profile(
        tenant_id: str,
        entity_type: str,
        entity_id: int
    ) -> EntityProfileResponse:
        """Return profile details for a salesperson or customer.
        entity_type: 'salesperson' or 'customer'
        entity_id: the Django pk (same ID returned by the dashboard rankings)
        """
        def _get():
            if entity_type == 'salesperson':
                try:
                    user = OdooUser.objects.get(id=entity_id, tenant_id=tenant_id)
                except OdooUser.DoesNotExist:
                    raise NotFoundError(f"Salesperson with id {entity_id} not found")
                # Try to find the linked partner for extra fields (phone, etc.)
                partner = Partner.objects.filter(
                    tenant_id=tenant_id, email=user.email
                ).first() if user.email else None
                return EntityProfileResponse(
                    entity_type='salesperson',
                    id=user.id,
                    odoo_id=user.odoo_id,
                    name=user.name,
                    email=user.email,
                    phone=partner.phone if partner else None,
                    city=partner.city if partner else None,
                    country_code=partner.country_code if partner else None,
                    is_active=user.is_active,
                    created_at=None,  # User model has no created_at
                )
            elif entity_type == 'customer':
                try:
                    p = Partner.objects.get(id=entity_id, tenant_id=tenant_id)
                except Partner.DoesNotExist:
                    raise NotFoundError(f"Customer with id {entity_id} not found")
                return EntityProfileResponse(
                    entity_type='customer',
                    id=p.id,
                    odoo_id=p.odoo_id,
                    name=p.name,
                    email=p.email,
                    phone=p.phone,
                    city=p.city,
                    country_code=p.country_code,
                    is_customer=p.is_customer,
                    is_supplier=p.is_supplier,
                    customer_rank=p.customer_rank,
                    supplier_rank=p.supplier_rank,
                    is_active=p.is_active,
                    created_at=p.created_at,
                )
            else:
                raise ValidationError(
                    f"Invalid entity_type '{entity_type}'. Must be 'salesperson' or 'customer'"
                )
        return await asyncio.to_thread(_get)

    # ── Product Sales Detail ───────────────────────────────────────────────

    @staticmethod
    async def get_product_sales_details(
        tenant_id: str,
        product_id: int,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        company_ids: Optional[list[int]] = None,
        base_currency: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> ProductSalesDetailResponse:
        """Return every sale-line for a specific product, with order context."""
        def _get():
            # Resolve product
            try:
                product = Product.objects.get(id=product_id, tenant_id=tenant_id)
            except Product.DoesNotExist:
                raise NotFoundError(f"Product with id {product_id} not found")

            initial_date = SalesService._parse_date(start_date)
            final_date = SalesService._parse_date(end_date)
            if not final_date:
                final_date = timezone.now().date()
            if not initial_date:
                initial_date = final_date - timedelta(days=30)

            lines_qs = SalesOrderLine.objects.filter(
                tenant_id=tenant_id,
                product_id=product_id,
                sales_order__state__in=['sale', 'done']
            )
            lines_qs = SalesService._apply_date_filter(
                lines_qs, initial_date, final_date, date_column="fact_sales_orders.date_order"
            ).select_related(
                'sales_order', 'sales_order__company', 'sales_order__partner', 'product'
            ).order_by('-sales_order__date_order')

            if company_ids:
                lines_qs = lines_qs.filter(sales_order__company_id__in=company_ids)

            effective_base = (base_currency or 'XAF').upper()
            rate_map = _get_rate_map()

            groups: dict[int, dict] = {}
            flat_lines = []
            total_revenue = 0.0
            total_qty = 0.0

            for line in lines_qs:
                order = line.sales_order
                company_obj = order.company if order else None
                cid   = company_obj.odoo_id if company_obj else None
                cname = company_obj.name     if company_obj else 'Unknown'

                if cid not in groups:
                    groups[cid] = {'company_id': cid, 'company_name': cname, 'metric_value': 0.0}

                code = order.currency_code or 'COMPANY_BASE' if order else 'COMPANY_BASE'
                rate = _get_conversion_rate(code, effective_base, rate_map)
                converted_subtotal = _to_float(line.price_subtotal) * rate
                converted_total = _to_float(line.price_total) * rate

                groups[cid]['metric_value'] += converted_total
                total_revenue += converted_total
                total_qty += _to_float(line.product_uom_qty)

                flat_lines.append(ProductSaleLineDetail(
                    line_id=line.id,
                    order_id=order.id if order else 0,
                    order_odoo_id=order.odoo_id if order else 0,
                    order_name=order.odoo_name if order else None,
                    date_order=order.date_order if order else None,
                    company_id=cid,
                    company_name=cname,
                    customer_name=order.partner.name if (order and order.partner) else None,
                    product_uom_qty=_to_float(line.product_uom_qty),
                    qty_delivered=_to_float(line.qty_delivered),
                    qty_invoiced=_to_float(line.qty_invoiced),
                    price_unit=_to_float(line.price_unit),
                    discount=_to_float(line.discount),
                    price_subtotal=_to_float(line.price_subtotal),
                    price_total=_to_float(line.price_total),
                    margin=_to_float(line.margin),
                    currency_code=code,
                    converted_subtotal=converted_subtotal,
                    converted_total=converted_total
                ))

            company_groups = [
                MetricDetailCompanyGroup(**g) for g in groups.values()
            ]

            total_items = len(flat_lines)
            paginated = flat_lines[offset:offset + limit]

            return ProductSalesDetailResponse(
                product_id=product.id,
                product_name=product.name,
                product_sku=product.default_code,
                product_type=product.product_type,
                list_price=_to_float(product.list_price) if product.list_price else None,
                base_currency=effective_base,
                total_revenue=total_revenue,
                total_qty_sold=total_qty,
                line_count=total_items,
                company_groups=company_groups,
                items=paginated,
                total=total_items,
                limit=limit,
                offset=offset
            )

        return await asyncio.to_thread(_get)

    # ── Customer Metrics ───────────────────────────────────────────────────

    @staticmethod
    async def get_customer_metrics(
        tenant_id: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        company_ids: Optional[list[int]] = None,
        partner_id: Optional[int] = None
    ) -> CustomerMetricsResponse:
        """Calculate and return Purchase Frequency and Customer Lifespan."""
        def _get():
            from django.db.models import Count, Min, Max
            
            initial_date = SalesService._parse_date(start_date)
            final_date = SalesService._parse_date(end_date)
            
            # Start with base queryset
            qs = SalesOrder.objects.filter(
                tenant_id=tenant_id, 
                state__in=['sale', 'done'],
                partner__isnull=False
            )
            
            # Apply date filters if provided
            qs = SalesService._apply_date_filter(qs, initial_date, final_date)
                
            # Apply company filters if provided
            if company_ids:
                qs = qs.filter(company_id__in=company_ids)
                
            # Apply partner filter if provided
            if partner_id:
                qs = qs.filter(partner_id=partner_id)

            qs = qs.values(
                'partner_id', 'partner__name'
            ).annotate(
                order_count=Count('id'),
                first_order=Min('date_order'),
                last_order=Max('date_order')
            )

            metrics = []
            total_lifespan_days = 0
            total_lifespan_months = 0.0
            total_frequency_year = 0.0
            total_frequency_month = 0.0

            for row in qs:
                pid = row['partner_id']
                pname = row['partner__name']
                count = row['order_count']
                first = row['first_order']
                last = row['last_order']
                
                # Lifespan
                diff = last - first
                lifespan_days = diff.days
                lifespan_months = lifespan_days / 30.44

                # Frequency
                if lifespan_days > 0:
                    freq_per_year = (count / lifespan_days) * 365.0
                else:
                    freq_per_year = float(count)
                    
                if lifespan_months > 0:
                    freq_per_month = count / lifespan_months
                else:
                    freq_per_month = float(count)

                metrics.append(CustomerMetric(
                    partner_id=pid,
                    partner_name=pname or "Unknown",
                    order_count=count,
                    first_order_date=first,
                    last_order_date=last,
                    lifespan_days=lifespan_days,
                    lifespan_months=round(lifespan_months, 2),
                    frequency_per_year=round(freq_per_year, 2),
                    frequency_per_month=round(freq_per_month, 2)
                ))

                total_lifespan_days += lifespan_days
                total_lifespan_months += lifespan_months
                total_frequency_year += freq_per_year
                total_frequency_month += freq_per_month

            total_customers = len(metrics)
            avg_lifespan_days = total_lifespan_days / total_customers if total_customers else 0
            avg_lifespan_months = total_lifespan_months / total_customers if total_customers else 0
            avg_freq_year = total_frequency_year / total_customers if total_customers else 0
            avg_freq_month = total_frequency_month / total_customers if total_customers else 0

            return CustomerMetricsResponse(
                tenant_id=tenant_id,
                average_lifespan_days=round(avg_lifespan_days, 2),
                average_lifespan_months=round(avg_lifespan_months, 2),
                average_frequency_per_year=round(avg_freq_year, 2),
                average_frequency_per_month=round(avg_freq_month, 2),
                total_customers=total_customers,
                items=metrics
            )
            
        return await asyncio.to_thread(_get)
