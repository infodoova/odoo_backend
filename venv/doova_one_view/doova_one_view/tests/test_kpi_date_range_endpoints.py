from django.test import TransactionTestCase
from decimal import Decimal
from datetime import datetime, timezone as dt_timezone, date, timedelta

from odoo_app.models import (
    Tenant, Company, SalesOrder, SalesOrderLine,
    PurchaseOrder, PurchaseOrderLine, Partner, Product, ProductCategory, AccountMove
)
from doova_one_view.api.kpi.service import KPIService
from doova_one_view.api.kpi.routes import (
    get_overview, get_summary,
    get_revenues, get_expenses, get_profits,
    get_top_products, get_bottom_products, get_top_customers,
    get_product_detail, get_customer_detail,
    get_receivables_aging, get_receivables_aging_detail,
    get_fast_moving_products, get_category_performance, get_currency_impact,
)


class KPIDateRangeEndpointsTestCase(TransactionTestCase):

    def setUp(self):
        self.tenant = Tenant.objects.create(
            name="Date Test Tenant",
            odoo_url="http://datetest.odoo.com",
            odoo_database="date_db",
            api_key_encrypted=b"encrypted_date_key",
            is_active=True
        )
        self.company = Company.objects.create(
            odoo_id=1,
            name="Date Test Company",
            currency_code="USD",
            tenant=self.tenant
        )

        self.category = ProductCategory.objects.create(
            odoo_id=1,
            name="Electronics",
            complete_name="All / Electronics",
            tenant=self.tenant
        )

        self.prod_1 = Product.objects.create(
            odoo_id=101,
            name="Laptop",
            default_code="LAP01",
            product_type="consu",
            standard_price=Decimal("400.00"),
            tenant=self.tenant,
            company=self.company,
            category=self.category
        )
        self.prod_2 = Product.objects.create(
            odoo_id=102,
            name="Phone",
            default_code="PH01",
            product_type="consu",
            standard_price=Decimal("200.00"),
            tenant=self.tenant,
            company=self.company,
            category=self.category
        )

        self.customer = Partner.objects.create(
            odoo_id=501,
            name="Alice Corp",
            is_customer=True,
            tenant=self.tenant,
            company=self.company
        )
        self.vendor = Partner.objects.create(
            odoo_id=502,
            name="Supplier Bob",
            is_customer=False,
            tenant=self.tenant,
            company=self.company
        )

        # Create orders spanning 3 months:
        # Jan 2026, Feb 2026, Mar 2026
        self.dt_jan = datetime(2026, 1, 15, 10, 0, 0, tzinfo=dt_timezone.utc)
        self.dt_feb = datetime(2026, 2, 15, 10, 0, 0, tzinfo=dt_timezone.utc)
        self.dt_mar = datetime(2026, 3, 15, 10, 0, 0, tzinfo=dt_timezone.utc)

        # Sales Orders
        # Jan: $1,000 Laptop
        self.so_jan = SalesOrder.objects.create(
            odoo_id=1001,
            odoo_name="SO-JAN",
            state="sale",
            amount_total=Decimal("1000.00"),
            amount_untaxed=Decimal("1000.00"),
            amount_tax=Decimal("0.00"),
            margin=Decimal("600.00"),
            currency_code="USD",
            date_order=self.dt_jan,
            tenant=self.tenant,
            company=self.company,
            partner=self.customer
        )
        SalesOrderLine.objects.create(
            odoo_id=10001,
            odoo_order_id=self.so_jan.odoo_id,
            sales_order=self.so_jan,
            product=self.prod_1,
            product_uom_qty=Decimal("1.0"),
            price_unit=Decimal("1000.00"),
            price_subtotal=Decimal("1000.00"),
            price_total=Decimal("1000.00"),
            margin=Decimal("600.00"),
            tenant=self.tenant,
            company=self.company
        )

        # Feb: $500 Phone
        self.so_feb = SalesOrder.objects.create(
            odoo_id=1002,
            odoo_name="SO-FEB",
            state="sale",
            amount_total=Decimal("500.00"),
            amount_untaxed=Decimal("500.00"),
            amount_tax=Decimal("0.00"),
            margin=Decimal("300.00"),
            currency_code="USD",
            date_order=self.dt_feb,
            tenant=self.tenant,
            company=self.company,
            partner=self.customer
        )
        SalesOrderLine.objects.create(
            odoo_id=10002,
            odoo_order_id=self.so_feb.odoo_id,
            sales_order=self.so_feb,
            product=self.prod_2,
            product_uom_qty=Decimal("1.0"),
            price_unit=Decimal("500.00"),
            price_subtotal=Decimal("500.00"),
            price_total=Decimal("500.00"),
            margin=Decimal("300.00"),
            tenant=self.tenant,
            company=self.company
        )

        # Mar: $2,000 Laptop (2 units)
        self.so_mar = SalesOrder.objects.create(
            odoo_id=1003,
            odoo_name="SO-MAR",
            state="sale",
            amount_total=Decimal("2000.00"),
            amount_untaxed=Decimal("2000.00"),
            amount_tax=Decimal("0.00"),
            margin=Decimal("1200.00"),
            currency_code="USD",
            date_order=self.dt_mar,
            tenant=self.tenant,
            company=self.company,
            partner=self.customer
        )
        SalesOrderLine.objects.create(
            odoo_id=10003,
            odoo_order_id=self.so_mar.odoo_id,
            sales_order=self.so_mar,
            product=self.prod_1,
            product_uom_qty=Decimal("2.0"),
            price_unit=Decimal("1000.00"),
            price_subtotal=Decimal("2000.00"),
            price_total=Decimal("2000.00"),
            margin=Decimal("1200.00"),
            tenant=self.tenant,
            company=self.company
        )

        # Purchase Orders (Expenses)
        # Jan: $300
        self.po_jan = PurchaseOrder.objects.create(
            odoo_id=2001,
            odoo_name="PO-JAN",
            state="purchase",
            amount_total=Decimal("300.00"),
            amount_untaxed=Decimal("300.00"),
            amount_tax=Decimal("0.00"),
            currency_code="USD",
            date_order=self.dt_jan,
            tenant=self.tenant,
            company=self.company,
            partner=self.vendor
        )
        PurchaseOrderLine.objects.create(
            odoo_id=20001,
            odoo_order_id=self.po_jan.odoo_id,
            purchase_order=self.po_jan,
            product=self.prod_1,
            product_qty=Decimal("1.0"),
            price_unit=Decimal("300.00"),
            price_subtotal=Decimal("300.00"),
            price_total=Decimal("300.00"),
            tenant=self.tenant,
            company=self.company
        )

        # Feb: $200
        self.po_feb = PurchaseOrder.objects.create(
            odoo_id=2002,
            odoo_name="PO-FEB",
            state="purchase",
            amount_total=Decimal("200.00"),
            amount_untaxed=Decimal("200.00"),
            amount_tax=Decimal("0.00"),
            currency_code="USD",
            date_order=self.dt_feb,
            tenant=self.tenant,
            company=self.company,
            partner=self.vendor
        )
        PurchaseOrderLine.objects.create(
            odoo_id=20002,
            odoo_order_id=self.po_feb.odoo_id,
            purchase_order=self.po_feb,
            product=self.prod_2,
            product_qty=Decimal("1.0"),
            price_unit=Decimal("200.00"),
            price_subtotal=Decimal("200.00"),
            price_total=Decimal("200.00"),
            tenant=self.tenant,
            company=self.company
        )

        # Invoices for aging tests
        # Invoice 1: Due Jan 10 2026 (Overdue relative to Feb 1 2026 by 22 days -> 1-30 bucket)
        self.inv_1 = AccountMove.objects.create(
            odoo_id=3001,
            odoo_name="INV/2026/001",
            move_type="out_invoice",
            state="posted",
            payment_state="not_paid",
            amount_total=Decimal("600.00"),
            amount_untaxed=Decimal("600.00"),
            amount_tax=Decimal("0.00"),
            amount_residual=Decimal("600.00"),
            currency_code="USD",
            date=date(2026, 1, 1),
            invoice_date=date(2026, 1, 1),
            invoice_date_due=date(2026, 1, 10),
            tenant=self.tenant,
            company=self.company,
            partner=self.customer
        )

        from odoo_app.models import StockMove, StockQuant
        # Create a stock move in Jan 2026: 10 Laptops ($400 ea = $4,000)
        StockMove.objects.create(
            odoo_id=9001,
            tenant=self.tenant,
            company=self.company,
            product=self.prod_1,
            product_uom_qty=Decimal("10.0"),
            quantity_done=Decimal("10.0"),
            location_src="Virtual/Vendors",
            location_dest="WH/Stock",
            date=self.dt_jan,
            state="done"
        )
        StockQuant.objects.create(
            odoo_id=8001,
            tenant=self.tenant,
            company=self.company,
            product=self.prod_1,
            quantity=Decimal("10.0"),
            reserved_quantity=Decimal("2.0")
        )

    async def test_get_revenues_date_range(self):
        """Test unified /revenues endpoint with date_from & date_to."""
        # All time
        res_all = await get_revenues(base_currency="USD")
        self.assertEqual(res_all["grand_revenue_amount"], 3500.0)
        self.assertEqual(res_all["revenue_count"], 3)
        self.assertEqual(len(res_all["items"]), 3)

        # Feb only (2026-02-01 to 2026-02-28)
        res_feb = await get_revenues(date_from="2026-02-01", date_to="2026-02-28", base_currency="USD")
        self.assertEqual(res_feb["grand_revenue_amount"], 500.0)
        self.assertEqual(res_feb["revenue_count"], 1)
        self.assertEqual(len(res_feb["items"]), 1)
        self.assertEqual(res_feb["items"][0]["name"], "SO-FEB")
        self.assertEqual(res_feb["applied_filters"]["date_from"], "2026-02-01")
        self.assertEqual(res_feb["applied_filters"]["date_to"], "2026-02-28")

        # Feb to Mar (2026-02-01 to 2026-03-31)
        res_feb_mar = await get_revenues(date_from="2026-02-01", date_to="2026-03-31", base_currency="USD")
        self.assertEqual(res_feb_mar["grand_revenue_amount"], 2500.0)
        self.assertEqual(res_feb_mar["revenue_count"], 2)
        self.assertEqual(len(res_feb_mar["items"]), 2)

    async def test_get_expenses_date_range(self):
        """Test unified /expenses endpoint with date_from & date_to."""
        # Jan only
        res_jan = await get_expenses(date_from="2026-01-01", date_to="2026-01-31", base_currency="USD")
        self.assertEqual(res_jan["grand_expense_amount"], 300.0)
        self.assertEqual(res_jan["expense_count"], 1)
        self.assertEqual(res_jan["items"][0]["name"], "PO-JAN")

        # All time
        res_all = await get_expenses(base_currency="USD")
        self.assertEqual(res_all["grand_expense_amount"], 500.0)
        self.assertEqual(res_all["expense_count"], 2)

    async def test_get_profits_date_range(self):
        """Test unified /profits endpoint with date_from & date_to."""
        # Feb only: Revenue = 500, Expense = 200, Net = 300
        res_feb = await get_profits(date_from="2026-02-01", date_to="2026-02-28", base_currency="USD")
        self.assertEqual(res_feb["grand_revenue_amount"], 500.0)
        self.assertEqual(res_feb["grand_expense_amount"], 200.0)
        self.assertEqual(res_feb["grand_net_profit"], 300.0)
        self.assertEqual(res_feb["revenue_count"], 1)
        self.assertEqual(res_feb["expense_count"], 1)
        self.assertEqual(len(res_feb["revenues"]), 1)
        self.assertEqual(len(res_feb["expenses"]), 1)

    async def test_top_and_bottom_products_date_range(self):
        """Test top-products and bottom-products respects date_from and date_to."""
        # Jan only: Only Laptop sold
        res_jan = await get_top_products(date_from="2026-01-01", date_to="2026-01-31", base_currency="USD")
        self.assertEqual(len(res_jan["products"]), 1)
        self.assertEqual(res_jan["products"][0]["name"], "Laptop")
        self.assertEqual(res_jan["products"][0]["revenue"], 1000.0)

        # Feb only: Only Phone sold
        res_feb = await get_top_products(date_from="2026-02-01", date_to="2026-02-28", base_currency="USD")
        self.assertEqual(len(res_feb["products"]), 1)
        self.assertEqual(res_feb["products"][0]["name"], "Phone")
        self.assertEqual(res_feb["products"][0]["revenue"], 500.0)

        # All time: Top is Laptop ($3000), Bottom is Phone ($500)
        res_top = await get_top_products(base_currency="USD")
        self.assertEqual(res_top["products"][0]["name"], "Laptop")
        self.assertEqual(res_top["products"][0]["revenue"], 3000.0)

        res_bottom = await get_bottom_products(base_currency="USD")
        self.assertEqual(res_bottom["products"][0]["name"], "Phone")
        self.assertEqual(res_bottom["products"][0]["revenue"], 500.0)

    async def test_product_detail_drill_down_date_range(self):
        """Test that /products/{id}/detail filters orders by date range."""
        # Product 1 (Laptop): Jan ($1000, 1 order), Mar ($2000, 1 order)
        # Filter for Jan only
        res_prod_jan = await get_product_detail(
            product_id=self.prod_1.id,
            date_from="2026-01-01",
            date_to="2026-01-31"
        )
        self.assertEqual(res_prod_jan["total_revenue"], 1000.0)
        self.assertEqual(res_prod_jan["total_quantity_sold"], 1.0)
        self.assertEqual(res_prod_jan["order_total"], 1)
        self.assertEqual(len(res_prod_jan["orders"]), 1)
        self.assertEqual(res_prod_jan["orders"][0]["order_number"], "SO-JAN")

        # Filter for Mar only
        res_prod_mar = await get_product_detail(
            product_id=self.prod_1.id,
            date_from="2026-03-01",
            date_to="2026-03-31"
        )
        self.assertEqual(res_prod_mar["total_revenue"], 2000.0)
        self.assertEqual(res_prod_mar["total_quantity_sold"], 2.0)
        self.assertEqual(res_prod_mar["order_total"], 1)
        self.assertEqual(res_prod_mar["orders"][0]["order_number"], "SO-MAR")

    async def test_customer_detail_drill_down_date_range(self):
        """Test that /customers/{id}/detail filters orders by date range."""
        # Filter for Feb only
        res_cust_feb = await get_customer_detail(
            customer_id=self.customer.id,
            date_from="2026-02-01",
            date_to="2026-02-28"
        )
        self.assertEqual(res_cust_feb["total_revenue"], 500.0)
        self.assertEqual(res_cust_feb["total_orders"], 1)
        self.assertEqual(res_cust_feb["order_total"], 1)
        self.assertEqual(len(res_cust_feb["orders"]), 1)
        self.assertEqual(res_cust_feb["orders"][0]["order_number"], "SO-FEB")

    async def test_category_performance_and_fast_moving_date_range(self):
        """Test category-performance and fast-moving-products with date ranges."""
        res_cat_jan = await get_category_performance(date_from="2026-01-01", date_to="2026-01-31")
        self.assertEqual(len(res_cat_jan["items"]), 1)
        self.assertEqual(res_cat_jan["items"][0]["revenue"], 1000.0)

        res_fast_mar = await get_fast_moving_products(date_from="2026-03-01", date_to="2026-03-31")
        self.assertEqual(len(res_fast_mar["items"]), 1)
        self.assertEqual(res_fast_mar["items"][0]["name"], "Laptop")
        self.assertEqual(res_fast_mar["items"][0]["quantity_sold"], 2.0)

    async def test_receivables_aging_as_of_date(self):
        """Test receivables-aging with as_of_date."""
        # As of 2026-02-01: inv_1 (due 2026-01-10) is 22 days overdue -> bucket 1-30 days
        res_aging = await get_receivables_aging(as_of_date="2026-02-01")
        bucket_1_30 = next(b for b in res_aging["buckets"] if b["bucket"] == "1-30 days")
        self.assertEqual(bucket_1_30["amount"], 600.0)
        self.assertEqual(bucket_1_30["count"], 1)

        # As of 2026-01-05: inv_1 (due 2026-01-10) is NOT overdue -> bucket current
        res_aging_curr = await get_receivables_aging(as_of_date="2026-01-05")
        bucket_curr = next(b for b in res_aging_curr["buckets"] if b["bucket"] == "current")
        self.assertEqual(bucket_curr["amount"], 600.0)
        self.assertEqual(bucket_curr["count"], 1)

        # Test detail endpoint
        res_detail = await get_receivables_aging_detail(bucket="1-30", as_of_date="2026-02-01")
        self.assertEqual(len(res_detail["tenants"]), 1)
        self.assertEqual(res_detail["tenants"][0]["items"][0]["invoice_number"], "INV/2026/001")

    async def test_overview_date_range(self):
        """Test that /kpi/overview metrics strictly respect date_from and date_to."""
        # 1. All-time (when dates are omitted)
        res_all = await get_overview(base_currency="USD")
        kpis_all = res_all["kpis"]
        self.assertEqual(kpis_all["revenue"]["value"], 3500.0)
        self.assertEqual(kpis_all["expenses"]["value"], 500.0)
        self.assertEqual(kpis_all["profit"]["value"], 3000.0)
        self.assertEqual(kpis_all["orders"]["value"], 3)
        self.assertEqual(kpis_all["average_order_value"]["value"], round(3500.0 / 3, 2))
        self.assertEqual(len(res_all["tenant_benchmarks"]), 1)
        self.assertEqual(res_all["tenant_benchmarks"][0]["revenue"], 3500.0)

        # 2. January only (2026-01-01 to 2026-01-31)
        res_jan = await get_overview(date_from="2026-01-01", date_to="2026-01-31", base_currency="USD")
        kpis_jan = res_jan["kpis"]
        self.assertEqual(kpis_jan["revenue"]["value"], 1000.0)
        self.assertEqual(kpis_jan["expenses"]["value"], 300.0)
        self.assertEqual(kpis_jan["profit"]["value"], 700.0)
        self.assertEqual(kpis_jan["orders"]["value"], 1)
        self.assertEqual(kpis_jan["average_order_value"]["value"], 1000.0)
        self.assertEqual(res_jan["tenant_benchmarks"][0]["revenue"], 1000.0)
        self.assertEqual(res_jan["applied_filters"]["date_from"], "2026-01-01")
        self.assertEqual(res_jan["applied_filters"]["date_to"], "2026-01-31")

        # 3. February only (2026-02-01 to 2026-02-28)
        # Bounded stats: Revenue = $500, Expenses = $200, Profit = $300, Orders = 1
        res_feb = await get_overview(date_from="2026-02-01", date_to="2026-02-28", base_currency="USD")
        kpis_feb = res_feb["kpis"]
        self.assertEqual(kpis_feb["revenue"]["value"], 500.0)
        self.assertEqual(kpis_feb["expenses"]["value"], 200.0)
        self.assertEqual(kpis_feb["profit"]["value"], 300.0)
        self.assertEqual(kpis_feb["orders"]["value"], 1)
        self.assertEqual(kpis_feb["average_order_value"]["value"], 500.0)
        self.assertEqual(res_feb["tenant_benchmarks"][0]["revenue"], 500.0)

        # Verify previous period comparison (28 days before Feb 1 -> Jan 4 to Jan 31, which contains Jan 15 with $1,000 revenue)
        self.assertEqual(kpis_feb["revenue"]["previous_value"], 1000.0)
        self.assertEqual(kpis_feb["revenue"]["change_pct"], -50.0)
        self.assertEqual(kpis_feb["expenses"]["previous_value"], 300.0)
        self.assertEqual(kpis_feb["orders"]["previous_value"], 1)

        # 4. Multi-month custom range (2026-02-01 to 2026-03-31)
        res_feb_mar = await get_overview(date_from="2026-02-01", date_to="2026-03-31", base_currency="USD")
        kpis_feb_mar = res_feb_mar["kpis"]
        self.assertEqual(kpis_feb_mar["revenue"]["value"], 2500.0)
        self.assertEqual(kpis_feb_mar["expenses"]["value"], 200.0)
        self.assertEqual(kpis_feb_mar["profit"]["value"], 2300.0)
        self.assertEqual(kpis_feb_mar["orders"]["value"], 2)

        # 5. Empty date range (no sales, no purchases in 2025)
        res_empty = await get_overview(date_from="2025-01-01", date_to="2025-12-31", base_currency="USD")
        kpis_empty = res_empty["kpis"]
        self.assertEqual(kpis_empty["revenue"]["value"], 0.0)
        self.assertEqual(kpis_empty["expenses"]["value"], 0.0)
        self.assertEqual(kpis_empty["profit"]["value"], 0.0)
        self.assertEqual(kpis_empty["orders"]["value"], 0)
        self.assertEqual(len(res_empty["tenant_benchmarks"]), 0)
        # NWC in 2025 has 0 receivables because inv_1 was created in 2026
        self.assertEqual(kpis_empty["net_working_capital"]["current_assets"]["accounts_receivable"]["value"], 0.0)

        # 6. Test NWC in 2026 (inv_1 created on 2026-01-01 is included in 2026 receivables)
        res_2026 = await get_overview(date_from="2026-01-01", date_to="2026-01-31", base_currency="USD")
        self.assertEqual(res_2026["kpis"]["net_working_capital"]["current_assets"]["accounts_receivable"]["value"], 600.0)

        # 7. Test /summary endpoint with date_from & date_to
        res_summary = await get_summary(date_from="2026-02-01", date_to="2026-02-28", base_currency="USD")
        self.assertEqual(res_summary["kpis"]["revenue"]["value"], 500.0)
        self.assertEqual(res_summary["kpis"]["expenses"]["value"], 200.0)
        self.assertEqual(res_summary["kpis"]["profit"]["value"], 300.0)

    async def test_inventory_valuation_and_risk_date_range(self):
        """Test that inventory valuation and risk metrics vary dynamically with date range."""
        # 1. In 2025: No stock moves yet -> historical inventory is 0.0
        res_2025 = await get_overview(date_from="2025-01-01", date_to="2025-12-31", base_currency="USD")
        self.assertEqual(res_2025["kpis"]["inventory_value"]["value"], 0.0)
        self.assertEqual(res_2025["kpis"]["net_working_capital"]["current_assets"]["inventory"], 0.0)

        # 2. In Jan 2026: StockMove created on Jan 15 is included ($4,000)
        res_jan_2026 = await get_overview(date_from="2026-01-01", date_to="2026-01-31", base_currency="USD")
        self.assertEqual(res_jan_2026["kpis"]["inventory_value"]["value"], 4000.0)
        self.assertEqual(res_jan_2026["kpis"]["net_working_capital"]["current_assets"]["inventory"], 4000.0)

        # 3. All-time / no dates specified: Live StockQuant is used ($4,000)
        res_all = await get_overview(base_currency="USD")
        self.assertEqual(res_all["kpis"]["inventory_value"]["value"], 4000.0)

    async def test_currency_impact_date_range(self):
        """Test that currency impact respects date ranges."""
        # Querying 2025: inv_1 (created in 2026) is excluded from unrealized FX
        res_2025 = await get_currency_impact(date_from="2025-01-01", date_to="2025-12-31", base_currency="USD")
        self.assertEqual(res_2025["unrealized_fx_impact"], 0.0)

    async def test_receivables_aging_date_range(self):
        """Test that receivables aging excludes future invoices."""
        # Querying as of 2025-12-31: inv_1 (created 2026-01-01) is excluded
        res_2025 = await get_receivables_aging(date_to="2025-12-31")
        self.assertEqual(res_2025["total_receivables"], 0.0)

        # Querying as of 2026-01-31: inv_1 is included ($600)
        res_2026 = await get_receivables_aging(date_to="2026-01-31")
        self.assertEqual(res_2026["total_receivables"], 600.0)

