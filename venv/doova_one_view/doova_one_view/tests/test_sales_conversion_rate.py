"""
Sales dashboard conversion rate is time based.

conversion_rate = confirmed orders / (quotes + orders that are not cancelled), counting only
orders whose order date falls inside the requested start_date..end_date.

Uses a temporary test database (Django creates and drops it).
"""

from datetime import datetime, timezone as dt_timezone

from django.test import TransactionTestCase

from doova_one_view.api.sales.service import SalesService
from odoo_app.models import Company, SalesOrder, Tenant


class SalesConversionRateTests(TransactionTestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(
            name="Sales Tenant", odoo_url="http://x.odoo.com", odoo_database="x_db",
            api_key_encrypted=b"k", is_active=True,
        )
        self.company = Company.objects.create(odoo_id=1, name="Sales Co", currency_code="XAF", tenant=self.tenant)
        self._n = 0

    def _order(self, state, on):
        self._n += 1
        return SalesOrder.objects.create(
            odoo_id=self._n, odoo_name=f"SO{self._n:05d}", state=state,
            date_order=datetime(on[0], on[1], on[2], 10, 0, tzinfo=dt_timezone.utc),
            amount_total=1000, currency_code="XAF", tenant=self.tenant, company=self.company,
        )

    async def _rate(self, start, end):
        from asgiref.sync import sync_to_async
        d = await SalesService.get_dashboard(
            tenant_id=str(self.tenant.id), start_date=start, end_date=end, base_currency="XAF"
        )
        return d.conversion_rate

    async def _seed(self):
        from asgiref.sync import sync_to_async
        await sync_to_async(self._seed_sync)()

    def _seed_sync(self):
        # 2026: 2 confirmed + 2 draft + 1 cancelled  -> 2 / 4 = 50%
        self._order("sale", (2026, 3, 1))
        self._order("sale", (2026, 3, 2))
        self._order("draft", (2026, 3, 3))
        self._order("draft", (2026, 3, 4))
        self._order("cancel", (2026, 3, 5))
        # 2025: 3 confirmed + 1 draft -> must not affect the 2026 figure
        self._order("sale", (2025, 6, 1))
        self._order("sale", (2025, 6, 2))
        self._order("done", (2025, 6, 3))
        self._order("draft", (2025, 6, 4))

    async def test_only_orders_in_the_period_are_counted(self):
        await self._seed()
        self.assertEqual(await self._rate("2026-01-01", "2026-12-31"), 50.0)

    async def test_other_period_gets_its_own_rate(self):
        await self._seed()
        self.assertEqual(await self._rate("2025-01-01", "2025-12-31"), 75.0)  # 3 / 4

    async def test_cancelled_orders_are_ignored(self):
        await self._seed()
        # the only 2026-03-05 order is cancelled: nothing in that day -> 0, not an error
        self.assertEqual(await self._rate("2026-03-05", "2026-03-05"), 0)

    async def test_period_with_no_orders_is_zero(self):
        await self._seed()
        self.assertEqual(await self._rate("2024-01-01", "2024-12-31"), 0)

    async def test_whole_range_covers_both_years(self):
        await self._seed()
        self.assertEqual(await self._rate("2025-01-01", "2026-12-31"), 5 / 8 * 100)  # 5 confirmed / 8
