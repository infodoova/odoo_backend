from django.test import TransactionTestCase
from decimal import Decimal
from datetime import date

from odoo_app.models import Tenant, Company, AccountMove, AccountMoveLine, StockQuant, Product
from doova_one_view.api.kpi.service import KPIService


class KPINetWorkingCapitalTestCase(TransactionTestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(
            name="NWC Tenant",
            odoo_url="http://nwc.odoo.com",
            odoo_database="nwc_db",
            api_key_encrypted=b"encrypted_key",
            is_active=True
        )

        self.company_1 = Company.objects.create(
            odoo_id=1,
            name="Alpha Corp",
            currency_code="USD",
            tenant=self.tenant
        )
        self.company_2 = Company.objects.create(
            odoo_id=2,
            name="Beta Ltd",
            currency_code="EUR",
            tenant=self.tenant
        )

        today = date.today()

        # Company 1 Cash ($10,000)
        move_cash_c1 = AccountMove.objects.create(
            odoo_id=1001,
            state="posted",
            move_type="entry",
            date=today,
            tenant=self.tenant,
            company=self.company_1
        )
        AccountMoveLine.objects.create(
            odoo_id=2001,
            odoo_move_id=1001,
            account_move=move_cash_c1,
            account_type="asset_cash",
            balance=Decimal("10000.00"),
            tenant=self.tenant,
            company=self.company_1
        )

        # Company 2 Cash ($5,000)
        move_cash_c2 = AccountMove.objects.create(
            odoo_id=1002,
            state="posted",
            move_type="entry",
            date=today,
            tenant=self.tenant,
            company=self.company_2
        )
        AccountMoveLine.objects.create(
            odoo_id=2002,
            odoo_move_id=1002,
            account_move=move_cash_c2,
            account_type="asset_cash",
            balance=Decimal("5000.00"),
            tenant=self.tenant,
            company=self.company_2
        )

        # Company 1 Receivables ($4,000)
        AccountMove.objects.create(
            odoo_id=1003,
            state="posted",
            move_type="out_invoice",
            payment_state="not_paid",
            amount_total=Decimal("4000.00"),
            amount_residual=Decimal("4000.00"),
            currency_code="USD",
            date=today,
            tenant=self.tenant,
            company=self.company_1
        )

        # Company 1 Payables ($3,000)
        AccountMove.objects.create(
            odoo_id=1004,
            state="posted",
            move_type="in_invoice",
            payment_state="not_paid",
            amount_total=Decimal("3000.00"),
            amount_residual=Decimal("3000.00"),
            currency_code="USD",
            date=today,
            tenant=self.tenant,
            company=self.company_1
        )


    async def test_all_companies_working_capital(self):
        overview = await KPIService.get_overview(date_from=None, date_to=None)
        nwc = overview["kpis"]["net_working_capital"]

        self.assertIn("working_capital_ratio", nwc)
        self.assertIn("quick_ratio", nwc)
        self.assertIn("health_status", nwc)
        self.assertIn("company_breakdown", nwc)

        # Consolidated cash = 10,000 + 5,000 = 15,000
        # AR = 4,000, Payables = 3,000
        # Current Assets = 15,000 + 4,000 = 19,000
        # Current Liabilities = 3,000
        # NWC = 19,000 - 3,000 = 16,000
        self.assertEqual(nwc["current_assets"]["cash_and_equivalents"], 15000.0)
        self.assertEqual(nwc["current_assets"]["accounts_receivable"]["value"], 4000.0)
        self.assertEqual(nwc["current_liabilities"]["accounts_payable"], 3000.0)
        self.assertEqual(nwc["value"], 16000.0)
        self.assertEqual(nwc["health_status"], "healthy")

        # Company Breakdown check
        breakdown = nwc["company_breakdown"]
        self.assertEqual(len(breakdown), 2)

        c1_data = next(c for c in breakdown if c["company_id"] == self.company_1.id)
        self.assertEqual(c1_data["company_name"], "Alpha Corp")
        self.assertEqual(c1_data["current_assets"]["cash_and_equivalents"], 10000.0)
        self.assertEqual(c1_data["current_assets"]["accounts_receivable"]["value"], 4000.0)
        self.assertEqual(c1_data["current_liabilities"]["accounts_payable"], 3000.0)
        self.assertEqual(c1_data["net_working_capital"], 11000.0)

    async def test_single_company_working_capital(self):
        overview = await KPIService.get_overview(date_from=None, date_to=None, company_ids=[self.company_1.id])
        nwc = overview["kpis"]["net_working_capital"]

        self.assertEqual(nwc["current_assets"]["cash_and_equivalents"], 10000.0)
        self.assertEqual(nwc["current_assets"]["accounts_receivable"]["value"], 4000.0)
        self.assertEqual(nwc["current_liabilities"]["accounts_payable"], 3000.0)
        self.assertEqual(nwc["value"], 11000.0)

        breakdown = nwc["company_breakdown"]
        self.assertEqual(len(breakdown), 1)
        self.assertEqual(breakdown[0]["company_id"], self.company_1.id)
