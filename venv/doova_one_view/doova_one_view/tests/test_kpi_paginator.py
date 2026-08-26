from django.test import TransactionTestCase
from decimal import Decimal
from datetime import datetime, timezone as dt_timezone

from odoo_app.models import Tenant, Company, SalesOrder, SalesOrderLine, Partner, Product, ProductCategory
from doova_one_view.api.kpi.service import KPIService


class KPIPaginatorTestCase(TransactionTestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(
            name="Test Tenant",
            odoo_url="http://test.odoo.com",
            odoo_database="test_db",
            api_key_encrypted=b"encrypted_key",
            is_active=True
        )
        self.company = Company.objects.create(
            odoo_id=1,
            name="Test Company",
            currency_code="USD",
            tenant=self.tenant
        )

        self.category_1 = ProductCategory.objects.create(
            odoo_id=10,
            name="Category A",
            complete_name="All / Category A",
            tenant=self.tenant
        )
        self.category_2 = ProductCategory.objects.create(
            odoo_id=20,
            name="Category B",
            complete_name="All / Category B",
            tenant=self.tenant
        )

        # Create 15 products
        self.products = []
        for i in range(1, 16):
            cat = self.category_1 if i % 2 == 1 else self.category_2
            prod = Product.objects.create(
                odoo_id=100 + i,
                name=f"Product {i:02d}",
                default_code=f"P{i:02d}",
                product_type="consu",
                tenant=self.tenant,
                company=self.company,
                category=cat
            )
            self.products.append(prod)

        # Create 15 customers
        self.customers = []
        for i in range(1, 16):
            cust = Partner.objects.create(
                odoo_id=500 + i,
                name=f"Customer {i:02d}",
                is_customer=True,
                tenant=self.tenant,
                company=self.company
            )
            self.customers.append(cust)

        now = datetime(2026, 5, 15, 12, 0, 0, tzinfo=dt_timezone.utc)

        # Create orders for each product & customer with different revenue amounts
        for i in range(15):
            so = SalesOrder.objects.create(
                odoo_id=2000 + i,
                odoo_name=f"SO{i+1:03d}",
                state="sale",
                amount_total=Decimal(str((i + 1) * 100)),
                amount_untaxed=Decimal(str((i + 1) * 90)),
                amount_tax=Decimal(str((i + 1) * 10)),
                currency_code="USD",
                date_order=now,
                tenant=self.tenant,
                company=self.company,
                partner=self.customers[i]
            )
            SalesOrderLine.objects.create(
                odoo_id=3000 + i,
                odoo_order_id=so.odoo_id,
                sales_order=so,
                product=self.products[i],
                tenant=self.tenant,
                product_uom_qty=Decimal(str(i + 1)),
                price_unit=Decimal("100.00"),
                price_subtotal=Decimal(str((i + 1) * 100)),
                price_total=Decimal(str((i + 1) * 100)),
                margin=Decimal(str((i + 1) * 40))
            )



    async def test_top_products_pagination(self):
        # Page 1: limit=5, offset=0
        page1 = await KPIService.get_top_products(limit=5, offset=0)
        self.assertEqual(len(page1["items"]), 5)
        self.assertEqual(page1["total"], 15)
        self.assertEqual(page1["limit"], 5)
        self.assertEqual(page1["offset"], 0)
        self.assertEqual(page1["items"][0]["name"], "Product 15")
        self.assertIn("gross_profit", page1["items"][0])
        self.assertIn("cogs", page1["items"][0])
        self.assertEqual(page1["items"][0]["gross_profit"], 600.0)
        self.assertEqual(page1["items"][0]["cogs"], 900.0)


        # Page 2: limit=5, offset=5
        page2 = await KPIService.get_top_products(limit=5, offset=5)
        self.assertEqual(len(page2["items"]), 5)
        self.assertTrue(page2["has_more"])
        self.assertEqual(page2["items"][0]["name"], "Product 10")

        # Page 3: limit=5, offset=10
        page3 = await KPIService.get_top_products(limit=5, offset=10)
        self.assertEqual(len(page3["items"]), 5)
        self.assertFalse(page3["has_more"])

        # Unlimited: limit=0, offset=0
        unlimited = await KPIService.get_top_products(limit=0, offset=0)
        self.assertEqual(len(unlimited["items"]), 15)
        self.assertFalse(unlimited["has_more"])

    async def test_top_customers_pagination(self):
        page1 = await KPIService.get_top_customers(limit=5, offset=0)
        self.assertEqual(len(page1["items"]), 5)
        self.assertEqual(page1["total"], 15)
        self.assertTrue(page1["has_more"])

        unlimited = await KPIService.get_top_customers(limit=0, offset=0)
        self.assertEqual(len(unlimited["items"]), 15)
        self.assertFalse(unlimited["has_more"])

    async def test_fast_moving_products_pagination(self):
        page1 = await KPIService.get_fast_moving_products(limit=5, offset=0)
        self.assertEqual(len(page1["items"]), 5)
        self.assertEqual(page1["total"], 15)
        self.assertTrue(page1["has_more"])

    async def test_bottom_products_last_sold_on(self):
        bottom = await KPIService.get_top_products(limit=5, offset=0, descending=False)
        self.assertEqual(len(bottom["items"]), 5)
        self.assertEqual(bottom["items"][0]["name"], "Product 01")
        self.assertIn("last_sold_on", bottom["items"][0])
        self.assertEqual(bottom["items"][0]["last_sold_on"], "2026-05-15")

    async def test_category_performance_pagination(self):
        res = await KPIService.get_category_performance(limit=10, offset=0)
        self.assertEqual(res["total"], 2)
        self.assertEqual(len(res["items"]), 2)
        self.assertFalse(res["has_more"])

