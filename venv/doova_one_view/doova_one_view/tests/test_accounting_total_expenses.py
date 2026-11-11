"""
Total expenses on the accounting dashboard and its drill-downs.

"Total expenses" = cost of revenue + operating expenses + depreciation, so that
revenue - total expenses = net profit (the same as Odoo's Profit and Loss report).
Taxes and interest are part of operating expenses and must not be added again.

Uses a temporary test database (Django creates and drops it).
"""

from datetime import date
from decimal import Decimal

from asgiref.sync import sync_to_async
from django.test import TransactionTestCase

from doova_one_view.api.accounting.service import AccountingService
from odoo_app.models import AccountMove, AccountMoveLine, Company, Tenant

DAY = date(2026, 3, 10)


class TotalExpensesTests(TransactionTestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(
            name="Expense Tenant", odoo_url="http://x.odoo.com", odoo_database="x_db",
            api_key_encrypted=b"k", is_active=True,
        )
        self.company = Company.objects.create(odoo_id=1, name="Expense Co", currency_code="XAF", tenant=self.tenant)
        self._n = 0

    def _move(self, lines, state="posted", on=DAY):
        """lines: list of (account_type, account_code, debit, credit)."""
        self._n += 1
        move = AccountMove.objects.create(
            odoo_id=1000 + self._n, state=state, move_type="entry", date=on,
            tenant=self.tenant, company=self.company,
        )
        for i, (atype, code, debit, credit) in enumerate(lines):
            AccountMoveLine.objects.create(
                odoo_id=10000 + self._n * 10 + i, odoo_move_id=move.odoo_id, account_move=move,
                account_type=atype, account_code=code, account_name=f"acct {code}",
                debit=Decimal(debit), credit=Decimal(credit), balance=Decimal(debit) - Decimal(credit),
                tenant=self.tenant, company=self.company,
            )
        return move

    def _seed(self):
        # revenue 1,000 | cost of revenue 600 | operating 150 (of which tax 20 and interest 10) | depreciation 50
        self._move([("income", "70100001", "0", "1000"), ("asset_receivable", "41100001", "1000", "0")])
        self._move([("expense_direct_cost", "60510001", "600", "0"), ("asset_current", "37000001", "0", "600")])
        self._move([("expense", "62000001", "120", "0"), ("expense", "69000001", "20", "0"),
                    ("expense", "67310001", "10", "0"), ("asset_cash", "57100001", "0", "150")])
        self._move([("expense_depreciation", "651260001", "50", "0"), ("asset_non_current", "28000001", "0", "50")])

    async def _dashboard(self):
        return await AccountingService.get_dashboard(
            tenant_id=str(self.tenant.id), start_date="2026-01-01", end_date="2026-12-31", base_currency="XAF"
        )

    async def test_total_expenses_is_cost_of_revenue_plus_operating_plus_depreciation(self):
        await sync_to_async(self._seed)()
        d = await self._dashboard()
        self.assertEqual(d["total_expenses"]["value"], 800.0)  # 600 + 150 + 50
        self.assertEqual(d["cost_of_revenue"]["value"], 600.0)
        self.assertEqual(d["operating_expenses"]["value"], 150.0)
        self.assertEqual(d["depreciation"]["value"], 50.0)

    async def test_revenue_minus_total_expenses_is_net_profit(self):
        await sync_to_async(self._seed)()
        d = await self._dashboard()
        self.assertEqual(d["total_revenue"]["value"] - d["total_expenses"]["value"], d["net_profit"]["value"])
        self.assertEqual(d["net_profit"]["value"], 200.0)

    async def test_taxes_and_interest_are_shown_but_not_added_twice(self):
        await sync_to_async(self._seed)()
        d = await self._dashboard()
        self.assertEqual(d["taxes_and_interest"]["value"], 30.0)
        self.assertLessEqual(d["taxes_and_interest"]["value"], d["operating_expenses"]["value"])
        self.assertNotEqual(d["total_expenses"]["value"], 830.0)

    async def test_drill_down_total_equals_the_card(self):
        await sync_to_async(self._seed)()
        d = await self._dashboard()
        m = await AccountingService.get_dashboard_metric_details(
            str(self.tenant.id), "total_expenses", "2026-01-01", "2026-12-31", None, "XAF", 50, 0
        )
        self.assertEqual(m["total_metric_value"], d["total_expenses"]["value"])
        # only the three entries that carry an expense are listed, not the revenue entry
        self.assertEqual(m["total"], 3)

    async def test_net_profit_drill_down_still_matches(self):
        await sync_to_async(self._seed)()
        d = await self._dashboard()
        m = await AccountingService.get_dashboard_metric_details(
            str(self.tenant.id), "net_profit", "2026-01-01", "2026-12-31", None, "XAF", 50, 0
        )
        self.assertEqual(m["total_metric_value"], d["net_profit"]["value"])

    async def test_expense_trend_adds_up_to_total_expenses(self):
        await sync_to_async(self._seed)()
        d = await self._dashboard()
        self.assertEqual(sum(p["value"] for p in d["expense_trend"]), d["total_expenses"]["value"])

    async def test_daily_moves_modal_uses_the_same_definition(self):
        await sync_to_async(self._seed)()
        res = await AccountingService.get_daily_moves(str(self.tenant.id), DAY.isoformat(), None, "XAF", 50, 0)
        self.assertEqual(res["total_expenses"], 800.0)
        self.assertEqual(res["total_revenue"] - res["total_expenses"], res["net_profit"])

    async def test_draft_entries_are_not_counted(self):
        await sync_to_async(self._seed)()
        await sync_to_async(self._move)([("expense_direct_cost", "60510001", "999", "0")], state="draft")
        d = await self._dashboard()
        self.assertEqual(d["total_expenses"]["value"], 800.0)

    async def test_entries_outside_the_period_are_not_counted(self):
        await sync_to_async(self._seed)()
        await sync_to_async(self._move)([("expense", "62000001", "777", "0")], on=date(2025, 12, 31))
        d = await self._dashboard()
        self.assertEqual(d["total_expenses"]["value"], 800.0)
