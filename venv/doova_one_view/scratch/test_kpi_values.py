import os
import django
from datetime import date
from decimal import Decimal

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "doova_one_view.settings")
django.setup()

from odoo_app.models import SalesOrder, PurchaseOrder, AccountMove, StockQuant
from django.db.models import Sum, Avg, Count, F, Q, DecimalField, ExpressionWrapper, Value
from django.db.models.functions import Coalesce

def _to_float(v):
    try: return float(v or 0)
    except: return 0.0

def _sum(qs, field):
    return _to_float(qs.aggregate(value=Coalesce(Sum(field), Decimal("0")))["value"])

def test_overview():
    today = date.today()
    print(f"Testing for today: {today}")
    
    sales = SalesOrder.objects.filter(state__in=["sale", "done"])
    # No date filter for this test to see total capacity
    
    sales_stats = sales.aggregate(
        total_revenue=Coalesce(Sum("amount_total"), Decimal("0")),
        order_count=Count("id"),
        avg_order_value=Coalesce(Avg("amount_total"), Decimal("0")),
        gross_margin=Coalesce(Sum("margin"), Decimal("0")),
    )
    
    dashboard_sales = SalesOrder.objects.filter(state__in=["sale", "done"])
    
    revenue_today = _sum(dashboard_sales.filter(date_order__date=today), "amount_total")
    revenue_month = _sum(dashboard_sales.filter(date_order__year=today.year, date_order__month=today.month), "amount_total")
    revenue_year = _sum(dashboard_sales.filter(date_order__year=today.year), "amount_total")
    
    print(f"Revenue Today: {revenue_today}")
    print(f"Revenue Month: {revenue_month}")
    print(f"Revenue Year: {revenue_year}")
    
    # Check if there's ANY data in May 2026 regardless of state
    any_may = SalesOrder.objects.filter(date_order__year=2026, date_order__month=5).count()
    print(f"Any Sales in May 2026 (including drafts): {any_may}")

if __name__ == "__main__":
    test_overview()
