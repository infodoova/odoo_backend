"""
Purchase dashboard: total purchase and order count leave out draft and cancelled orders.

A draft is an unsent quotation and a cancelled order never happened, so neither is a purchase.
The state breakdown still reports every state, and the drill-down lists the same orders the
card counts.

Uses a temporary test database (Django creates and drops it).
"""

from datetime import datetime, timezone as dt_timezone

from asgiref.sync import sync_to_async
from django.test import TransactionTestCase

from doova_one_view.api.purchase.service import PurchaseService
from odoo_app.models import Company, PurchaseOrder, Tenant


class PurchaseExcludesDraftAndCancelTests(TransactionTestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(
            name="Purchase Tenant", odoo_url="http://x.odoo.com", odoo_database="x_db",
            api_key_encrypted=b"k", is_active=True,
        )
        self.company = Company.objects.create(odoo_id=1, name="Purchase Co", currency_code="XAF", tenant=self.tenant)
        self._n = 0

    def _order(self, state, amount, on=(2026, 3, 1)):
        self._n += 1
        return PurchaseOrder.objects.create(
            odoo_id=self._n, odoo_name=f"PO{self._n:05d}", state=state,
            date_order=datetime(on[0], on[1], on[2], 10, 0, tzinfo=dt_timezone.utc),
            amount_total=amount, currency_code="XAF", tenant=self.tenant, company=self.company,
        )

    def _seed_sync(self):
        self._order("purchase", 1000)
        self._order("purchase", 3000)
        self._order("done", 2000)
        self._order("draft", 9000)
        self._order("cancel", 7000)
        # outside 2026: not part of the dashboard period
        self._order("purchase", 500, on=(2025, 5, 1))

    async def _dashboard(self):
        await sync_to_async(self._seed_sync)()
        return await PurchaseService.get_dashboard(
            tenant_id=str(self.tenant.id), start_date="2026-01-01", end_date="2026-12-31", base_currency="XAF"
        )

    async def test_total_purchase_excludes_draft_and_cancelled(self):
        d = await self._dashboard()
        self.assertEqual(d["total_purchase"]["value"], 6000.0)  # 1000 + 3000 + 2000

    async def test_order_count_excludes_draft_and_cancelled(self):
        d = await self._dashboard()
        self.assertEqual(d["order_count"], 3)

    async def test_average_order_value_uses_the_same_orders(self):
        d = await self._dashboard()
        self.assertEqual(d["avg_order_value"]["value"], 2000.0)  # 6000 / 3

    async def test_state_breakdown_still_shows_every_state(self):
        d = await self._dashboard()
        self.assertEqual(d["state_distribution"], {"purchase": 2, "done": 1, "draft": 1, "cancel": 1})
        self.assertEqual(d["draft_count"], 1)

    async def test_spend_summary_year_matches_total_purchase(self):
        d = await self._dashboard()
        self.assertEqual(d["spend_summary"]["year"], 6000.0)

    async def test_drill_down_matches_the_card(self):
        await self._dashboard()
        for metric, expected in (("total_purchase", 6000.0), ("order_count", 3.0)):
            m = await PurchaseService.get_dashboard_metric_details(
                str(self.tenant.id), metric, "2026-01-01", "2026-12-31", None, "XAF", 50, 0
            )
            self.assertEqual(m["total_metric_value"], expected, metric)
            self.assertEqual(m["total"], 3, metric)
            states = {i["state"] for i in m["items"]}
            self.assertNotIn("draft", states)
            self.assertNotIn("cancel", states)
