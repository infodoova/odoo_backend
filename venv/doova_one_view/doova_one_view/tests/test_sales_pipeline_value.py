"""
Sales dashboard pipeline value is time based.

pipeline_value = total amount (tax included) of open quotations (draft / sent) whose order date
falls inside the requested start_date..end_date. Confirmed and cancelled orders are not included.

Uses a temporary test database (Django creates and drops it).
"""

from datetime import datetime, timezone as dt_timezone

from asgiref.sync import sync_to_async
from django.test import TransactionTestCase

from doova_one_view.api.sales.service import SalesService
from odoo_app.models import Company, SalesOrder, Tenant


class SalesPipelineValueTests(TransactionTestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(
            name="Pipeline Tenant", odoo_url="http://x.odoo.com", odoo_database="x_db",
            api_key_encrypted=b"k", is_active=True,
        )
        self.company = Company.objects.create(odoo_id=1, name="Pipeline Co", currency_code="XAF", tenant=self.tenant)
        self._n = 0

    def _order(self, state, on, amount):
        self._n += 1
        return SalesOrder.objects.create(
            odoo_id=self._n, odoo_name=f"SO{self._n:05d}", state=state,
            date_order=datetime(on[0], on[1], on[2], 10, 0, tzinfo=dt_timezone.utc),
            amount_total=amount, currency_code="XAF", tenant=self.tenant, company=self.company,
        )

    def _seed_sync(self):
        # 2026: open quotes 100 (draft) + 200 (sent); a confirmed 5000 and a cancelled 7000 do not count
        self._order("draft", (2026, 3, 1), 100)
        self._order("sent", (2026, 3, 2), 200)
        self._order("sale", (2026, 3, 3), 5000)
        self._order("cancel", (2026, 3, 4), 7000)
        # 2025: open quote 1000 must not count for 2026
        self._order("draft", (2025, 6, 1), 1000)

    async def _pipeline(self, start, end):
        await sync_to_async(self._seed_sync)()
        d = await SalesService.get_dashboard(
            tenant_id=str(self.tenant.id), start_date=start, end_date=end, base_currency="XAF"
        )
        return d.pipeline_value.value

    async def test_only_open_quotes_in_the_period_are_counted(self):
        self.assertEqual(await self._pipeline("2026-01-01", "2026-12-31"), 300.0)

    async def test_other_period_has_its_own_pipeline(self):
        self.assertEqual(await self._pipeline("2025-01-01", "2025-12-31"), 1000.0)

    async def test_range_across_years_adds_both(self):
        self.assertEqual(await self._pipeline("2025-01-01", "2026-12-31"), 1300.0)

    async def test_period_without_quotes_is_zero(self):
        self.assertEqual(await self._pipeline("2024-01-01", "2024-12-31"), 0.0)

    async def test_confirmed_and_cancelled_orders_are_excluded(self):
        # the 2026-03-03 order is confirmed and the 2026-03-04 one is cancelled: nothing open on those days
        self.assertEqual(await self._pipeline("2026-03-03", "2026-03-04"), 0.0)
