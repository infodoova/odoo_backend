from django.test import TransactionTestCase
from decimal import Decimal
from datetime import date

from odoo_app.models import Tenant, Company, AccountMove, AccountMoveLine
from doova_one_view.api.accounting.service import AccountingService


class AccountingTotalAssetsTestCase(TransactionTestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(
            name="Asset Tenant",
            odoo_url="http://assets.odoo.com",
            odoo_database="assets_db",
            api_key_encrypted=b"encrypted_key",
            is_active=True
        )

        self.company = Company.objects.create(
            odoo_id=1,
            name="Asset Company",
            currency_code="USD",
            tenant=self.tenant
        )

        today = date.today()

        # Posted Move 1: Cash Asset ($50,000)
        move_cash = AccountMove.objects.create(
            odoo_id=9001,
            state="posted",
            move_type="entry",
            date=today,
            tenant=self.tenant,
            company=self.company
        )
        AccountMoveLine.objects.create(
            odoo_id=9101,
            odoo_move_id=9001,
            account_move=move_cash,
            account_type="asset_cash",
            debit=Decimal("50000.00"),
            credit=Decimal("0.00"),
            balance=Decimal("50000.00"),
            tenant=self.tenant,
            company=self.company
        )

        # Posted Move 2: Fixed Asset ($120,000)
        move_fixed = AccountMove.objects.create(
            odoo_id=9002,
            state="posted",
            move_type="entry",
            date=today,
            tenant=self.tenant,
            company=self.company
        )
        AccountMoveLine.objects.create(
            odoo_id=9102,
            odoo_move_id=9002,
            account_move=move_fixed,
            account_type="asset_fixed",
            debit=Decimal("120000.00"),
            credit=Decimal("0.00"),
            balance=Decimal("120000.00"),
            tenant=self.tenant,
            company=self.company
        )

        # Posted Move 3: Current Asset ($30,000)
        move_current = AccountMove.objects.create(
            odoo_id=9003,
            state="posted",
            move_type="entry",
            date=today,
            tenant=self.tenant,
            company=self.company
        )
        AccountMoveLine.objects.create(
            odoo_id=9103,
            odoo_move_id=9003,
            account_move=move_current,
            account_type="asset_current",
            debit=Decimal("30000.00"),
            credit=Decimal("0.00"),
            balance=Decimal("30000.00"),
            tenant=self.tenant,
            company=self.company
        )

    async def test_dashboard_total_assets(self):
        res = await AccountingService.get_dashboard(tenant_id=str(self.tenant.id), base_currency="USD")

        self.assertIn("total_assets", res)
        self.assertIn("total_assets_value", res)
        self.assertIn("asset_breakdown", res)

        # Total Assets = 50,000 (cash) + 120,000 (fixed) + 30,000 (current) = 200,000
        self.assertEqual(res["total_assets_value"], 200000.0)
        self.assertEqual(res["total_assets"]["value"], 200000.0)

        breakdown = res["asset_breakdown"]
        self.assertEqual(breakdown["cash_and_equivalents"], 50000.0)
        self.assertEqual(breakdown["fixed_assets"], 120000.0)
        self.assertEqual(breakdown["current_assets"], 30000.0)
