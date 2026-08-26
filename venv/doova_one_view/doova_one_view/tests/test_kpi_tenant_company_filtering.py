from django.test import TransactionTestCase
from decimal import Decimal
from datetime import date

from odoo_app.models import Tenant, Company, SalesOrder, PurchaseOrder, StockQuant, Partner, Product
from doova_one_view.api.kpi.service import KPIService, _apply_tenant_company_filter
from doova_one_view.api.kpi.routes import _parse_csv_str, _parse_csv_int


class KPITenantCompanyFilteringTestCase(TransactionTestCase):

    def setUp(self):
        self.tenant_1 = Tenant.objects.create(
            name="Tenant 1",
            odoo_url="http://t1.odoo.com",
            odoo_database="db1",
            api_key_encrypted=b"encrypted_key_1",
            is_active=True
        )
        self.tenant_2 = Tenant.objects.create(
            name="Tenant 2",
            odoo_url="http://t2.odoo.com",
            odoo_database="db2",
            api_key_encrypted=b"encrypted_key_2",
            is_active=True
        )


        self.company_1 = Company.objects.create(
            odoo_id=1,
            name="Company 1",
            currency_code="USD",
            tenant=self.tenant_1
        )
        self.company_2 = Company.objects.create(
            odoo_id=2,
            name="Company 2",
            currency_code="EUR",
            tenant=self.tenant_2
        )

        self.partner_1 = Partner.objects.create(
            odoo_id=101,
            name="Customer A",
            is_customer=True,
            tenant=self.tenant_1,
            company=self.company_1
        )
        self.partner_2 = Partner.objects.create(
            odoo_id=102,
            name="Customer B",
            is_customer=True,
            tenant=self.tenant_2,
            company=self.company_2
        )

        from datetime import datetime, timezone as dt_timezone
        fixed_dt = datetime(2026, 5, 15, 12, 0, 0, tzinfo=dt_timezone.utc)

        self.so_1 = SalesOrder.objects.create(
            odoo_id=1001,
            odoo_name="SO001",
            state="sale",
            amount_total=Decimal("500.00"),
            amount_untaxed=Decimal("450.00"),
            amount_tax=Decimal("50.00"),
            currency_code="USD",
            date_order=fixed_dt,
            tenant=self.tenant_1,
            company=self.company_1,
            partner=self.partner_1
        )
        self.so_2 = SalesOrder.objects.create(
            odoo_id=1002,
            odoo_name="SO002",
            state="sale",
            amount_total=Decimal("1200.00"),
            amount_untaxed=Decimal("1000.00"),
            amount_tax=Decimal("200.00"),
            currency_code="EUR",
            date_order=fixed_dt,
            tenant=self.tenant_2,
            company=self.company_2,
            partner=self.partner_2
        )

        self.po_1 = PurchaseOrder.objects.create(
            odoo_id=2001,
            odoo_name="PO001",
            state="purchase",
            amount_total=Decimal("200.00"),
            amount_untaxed=Decimal("180.00"),
            amount_tax=Decimal("20.00"),
            currency_code="USD",
            date_order=fixed_dt,
            tenant=self.tenant_1,
            company=self.company_1,
            partner=self.partner_1
        )

    def test_csv_parser_helpers(self):
        self.assertIsNone(_parse_csv_str(None))
        self.assertIsNone(_parse_csv_str("   ,  "))
        self.assertEqual(_parse_csv_str("t1, t2"), ["t1", "t2"])

        self.assertIsNone(_parse_csv_int(None))
        self.assertIsNone(_parse_csv_int("abc, xyz"))
        self.assertEqual(_parse_csv_int("1, 2, invalid, 3"), [1, 2, 3])

    def test_apply_tenant_company_filter(self):
        qs = SalesOrder.objects.all()

        t1_filtered = _apply_tenant_company_filter(qs, tenant_ids=[str(self.tenant_1.id)])
        self.assertEqual(t1_filtered.count(), 1)
        self.assertEqual(t1_filtered.first(), self.so_1)

        c2_filtered = _apply_tenant_company_filter(qs, company_ids=[self.company_2.id])
        self.assertEqual(c2_filtered.count(), 1)
        self.assertEqual(c2_filtered.first(), self.so_2)

        both_filtered = _apply_tenant_company_filter(qs, tenant_ids=[str(self.tenant_1.id)], company_ids=[self.company_2.id])
        self.assertEqual(both_filtered.count(), 0)

    async def test_kpi_service_overview_filtering(self):
        res_all = await KPIService.get_overview(date_from=None, date_to=None)
        self.assertIn("applied_filters", res_all)

        res_t1 = await KPIService.get_overview(
            date_from=None,
            date_to=None,
            tenant_ids=[str(self.tenant_1.id)]
        )
        self.assertEqual(res_t1["applied_filters"]["tenant_ids"], [str(self.tenant_1.id)])

        res_c2 = await KPIService.get_overview(
            date_from=None,
            date_to=None,
            company_ids=[self.company_2.id]
        )
        self.assertEqual(res_c2["applied_filters"]["company_ids"], [self.company_2.id])

    async def test_kpi_service_period_detail_filtering(self):
        res_t1 = await KPIService.get_period_detail(
            kind="revenues",
            period="monthly",
            date_str="2026-05-15",
            tenant_ids=[str(self.tenant_1.id)]
        )
        self.assertEqual(res_t1["revenue_count"], 1)
        self.assertEqual(res_t1["applied_filters"]["tenant_ids"], [str(self.tenant_1.id)])

        res_c2 = await KPIService.get_period_detail(
            kind="revenues",
            period="monthly",
            date_str="2026-05-15",
            company_ids=[self.company_2.id]
        )
        self.assertEqual(res_c2["revenue_count"], 1)
        self.assertEqual(res_c2["applied_filters"]["company_ids"], [self.company_2.id])



