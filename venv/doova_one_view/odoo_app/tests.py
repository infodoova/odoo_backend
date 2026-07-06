from datetime import date, timedelta
from django.test import TransactionTestCase
from asgiref.sync import async_to_sync
from odoo_app.models import Tenant, Company, Partner, AccountMove, AccountMoveLine
from doova_one_view.api.accounting.service import AccountingService


class TodayExpensesTestCase(TransactionTestCase):
    def setUp(self):
        # Create a tenant
        self.tenant = Tenant.objects.create(
            name="Test Tenant",
            odoo_url="https://test.odoo.com",
            odoo_database="test_db"
        )
        # Create a company
        self.company = Company.objects.create(
            tenant=self.tenant,
            odoo_id=1,
            name="Test Company",
            currency_code="USD"
        )
        # Create a partner (vendor)
        self.vendor = Partner.objects.create(
            tenant=self.tenant,
            odoo_id=10,
            name="Test Vendor",
            is_supplier=True
        )

    def test_get_today_expenses_empty(self):
        # Retrieve today's expenses when none exist
        result = async_to_sync(AccountingService.get_today_expenses)(str(self.tenant.id))
        self.assertEqual(result["total_count"], 0)
        self.assertEqual(result["total_amount"], 0.0)
        self.assertEqual(result["items"], [])

    def test_get_today_expenses_with_data(self):
        today_date = date.today()
        yesterday_date = today_date - timedelta(days=1)

        # 1. Create a posted vendor bill for today (Expense)
        bill_today = AccountMove.objects.create(
            tenant=self.tenant,
            company=self.company,
            odoo_id=101,
            odoo_name="BILL/2026/07/0001",
            partner=self.vendor,
            date=today_date,
            move_type="in_invoice",
            state="posted",
            amount_total=150.50,
            currency_code="USD"
        )
        # Add a line to today's bill
        AccountMoveLine.objects.create(
            tenant=self.tenant,
            account_move=bill_today,
            odoo_id=201,
            odoo_move_id=101,
            partner=self.vendor,
            company=self.company,
            account_name="Office Supplies Expense",
            price_subtotal=150.50,
            quantity=1,
            price_unit=150.50
        )

        # 2. Create a draft vendor bill for today (Should not be counted since state != 'posted')
        draft_bill = AccountMove.objects.create(
            tenant=self.tenant,
            company=self.company,
            odoo_id=102,
            odoo_name="BILL/2026/07/0002",
            partner=self.vendor,
            date=today_date,
            move_type="in_invoice",
            state="draft",
            amount_total=99.99,
            currency_code="USD"
        )
        AccountMoveLine.objects.create(
            tenant=self.tenant,
            account_move=draft_bill,
            odoo_id=202,
            odoo_move_id=102,
            partner=self.vendor,
            company=self.company,
            account_name="Rent Expense",
            price_subtotal=99.99
        )

        # 3. Create a posted vendor bill for yesterday (Should not be counted in today's default view)
        bill_yesterday = AccountMove.objects.create(
            tenant=self.tenant,
            company=self.company,
            odoo_id=103,
            odoo_name="BILL/2026/07/0003",
            partner=self.vendor,
            date=yesterday_date,
            move_type="in_invoice",
            state="posted",
            amount_total=500.00,
            currency_code="USD"
        )
        AccountMoveLine.objects.create(
            tenant=self.tenant,
            account_move=bill_yesterday,
            odoo_id=203,
            odoo_move_id=103,
            partner=self.vendor,
            company=self.company,
            account_name="Travel Expense",
            price_subtotal=500.00
        )

        # Retrieve today's expenses
        result = async_to_sync(AccountingService.get_today_expenses)(str(self.tenant.id))
        self.assertEqual(result["total_count"], 1)
        self.assertEqual(result["total_amount"], 150.50)
        self.assertEqual(len(result["items"]), 1)

        item = result["items"][0]
        self.assertEqual(item["id"], bill_today.id)
        self.assertEqual(item["amount"], 150.50)
        self.assertEqual(item["source"], "Test Vendor")
        self.assertEqual(item["categories"], ["Office Supplies Expense"])
        self.assertEqual(item["category_summary"], "Office Supplies Expense")
        self.assertEqual(item["date"], today_date.isoformat())

        # Retrieve yesterday's expenses explicitly using date override
        result_yesterday = async_to_sync(AccountingService.get_today_expenses)(
            str(self.tenant.id), yesterday_date.isoformat()
        )
        self.assertEqual(result_yesterday["total_count"], 1)
        self.assertEqual(result_yesterday["total_amount"], 500.0)
        self.assertEqual(result_yesterday["items"][0]["categories"], ["Travel Expense"])


class TenantResolutionTestCase(TransactionTestCase):
    """Tests for route-level automatic tenant resolution via UserTenantAccess."""

    def setUp(self):
        from odoo_app.models.app_user import AppUser
        from odoo_app.models.user_tenant_access import UserTenantAccess

        # Create two tenants
        self.tenant_a = Tenant.objects.create(
            name="Alpha Tenant",
            odoo_url="https://alpha.odoo.com",
            odoo_database="alpha_db"
        )
        self.tenant_b = Tenant.objects.create(
            name="Beta Tenant",
            odoo_url="https://beta.odoo.com",
            odoo_database="beta_db"
        )
        # Create an app user
        self.user = AppUser.objects.create(
            email="route_test@example.com",
            password_hash="hashed_password",
            full_name="Route Test User",
            is_active=True
        )
        # Link user to both tenants
        UserTenantAccess.objects.create(user=self.user, tenant=self.tenant_a)
        UserTenantAccess.objects.create(user=self.user, tenant=self.tenant_b)

    def test_all_tenants_resolved_from_user(self):
        """_get_all_tenants_for_user should return all linked tenant ids and names."""
        from doova_one_view.api.accounting.routes import _get_all_tenants_for_user
        tenants = async_to_sync(_get_all_tenants_for_user)(self.user)
        tenant_ids = {t["id"] for t in tenants}
        tenant_names = {t["name"] for t in tenants}
        self.assertIn(str(self.tenant_a.id), tenant_ids)
        self.assertIn(str(self.tenant_b.id), tenant_ids)
        self.assertIn("Alpha Tenant", tenant_names)
        self.assertIn("Beta Tenant", tenant_names)

    def test_no_tenant_raises_http_exception(self):
        """_get_all_tenants_for_user should raise HTTPException when user has no tenant access."""
        from fastapi import HTTPException
        from odoo_app.models.app_user import AppUser
        # Create a user with no tenant link
        orphan_user = AppUser.objects.create(
            email="orphan@example.com",
            password_hash="hashed_password",
            is_active=True
        )
        from doova_one_view.api.accounting.routes import _get_all_tenants_for_user
        with self.assertRaises(HTTPException) as ctx:
            async_to_sync(_get_all_tenants_for_user)(orphan_user)
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("No tenants", ctx.exception.detail)


class MultiTenantExpensesTestCase(TransactionTestCase):
    """Tests the multi-tenant grouped response from get_today_expenses service."""

    def setUp(self):
        from odoo_app.models.app_user import AppUser
        from odoo_app.models.user_tenant_access import UserTenantAccess

        today = date.today()

        # Tenant A with one posted expense today
        self.tenant_a = Tenant.objects.create(
            name="Company A", odoo_url="https://a.odoo.com", odoo_database="a_db"
        )
        partner_a = Partner.objects.create(
            tenant=self.tenant_a, odoo_id=1, name="Vendor A", is_supplier=True
        )
        company_a = Company.objects.create(
            tenant=self.tenant_a, odoo_id=1, name="Company A", currency_code="USD"
        )
        move_a = AccountMove.objects.create(
            tenant=self.tenant_a, company=company_a, partner=partner_a,
            odoo_id=1001, odoo_name="BILL-A-001", date=today,
            move_type="in_invoice", state="posted",
            amount_total=200.00, currency_code="USD"
        )
        AccountMoveLine.objects.create(
            tenant=self.tenant_a, account_move=move_a, partner=partner_a,
            company=company_a, odoo_id=2001, odoo_move_id=1001,
            account_name="Marketing Expense", price_subtotal=200.00
        )

        # Tenant B with two posted expenses today
        self.tenant_b = Tenant.objects.create(
            name="Company B", odoo_url="https://b.odoo.com", odoo_database="b_db"
        )
        partner_b = Partner.objects.create(
            tenant=self.tenant_b, odoo_id=2, name="Vendor B", is_supplier=True
        )
        company_b = Company.objects.create(
            tenant=self.tenant_b, odoo_id=2, name="Company B", currency_code="USD"
        )
        move_b1 = AccountMove.objects.create(
            tenant=self.tenant_b, company=company_b, partner=partner_b,
            odoo_id=1002, odoo_name="BILL-B-001", date=today,
            move_type="in_invoice", state="posted",
            amount_total=350.00, currency_code="USD"
        )
        AccountMoveLine.objects.create(
            tenant=self.tenant_b, account_move=move_b1, partner=partner_b,
            company=company_b, odoo_id=2002, odoo_move_id=1002,
            account_name="Utilities Expense", price_subtotal=350.00
        )
        move_b2 = AccountMove.objects.create(
            tenant=self.tenant_b, company=company_b, partner=partner_b,
            odoo_id=1003, odoo_name="BILL-B-002", date=today,
            move_type="in_invoice", state="posted",
            amount_total=50.00, currency_code="USD"
        )
        AccountMoveLine.objects.create(
            tenant=self.tenant_b, account_move=move_b2, partner=partner_b,
            company=company_b, odoo_id=2003, odoo_move_id=1003,
            account_name="Office Supplies", price_subtotal=50.00
        )

    def test_expenses_separated_by_tenant(self):
        """Expenses for each tenant are isolated and correctly totalled."""
        result_a = async_to_sync(AccountingService.get_today_expenses)(str(self.tenant_a.id))
        result_b = async_to_sync(AccountingService.get_today_expenses)(str(self.tenant_b.id))

        # Tenant A: 1 item, $200
        self.assertEqual(result_a["total_count"], 1)
        self.assertEqual(result_a["total_amount"], 200.00)
        self.assertEqual(result_a["items"][0]["source"], "Vendor A")

        # Tenant B: 2 items, $400
        self.assertEqual(result_b["total_count"], 2)
        self.assertEqual(result_b["total_amount"], 400.00)
        sources_b = {item["source"] for item in result_b["items"]}
        self.assertEqual(sources_b, {"Vendor B"})

        # No cross-contamination: Tenant A does not see Tenant B's data
        names_a = {item["name"] for item in result_a["items"]}
        self.assertNotIn("BILL-B-001", names_a)
