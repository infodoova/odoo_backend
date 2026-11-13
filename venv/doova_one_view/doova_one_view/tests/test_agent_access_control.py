"""
Agent access control: tenant scope, session ownership, signed report links, rate limiter.

These cover the server-side decisions that used to be left to the request body:
a user may only read their own tenants through the agent, and only their own chat sessions.

Uses a temporary test database (Django creates and drops it).
"""

from django.test import TestCase
from fastapi import HTTPException

from doova_one_view.api.agent import access
from doova_one_view.api.agent.query_context import build_tenant_filter_sql, normalize_tenant_ids
from doova_one_view.api.agent.session_context import (
    get_authorized_tenant_ids,
    run_in_scope,
    set_authorized_tenant_ids,
)
from doova_one_view.api.agent.session_manager import SessionAccessDenied, SessionManager
from doova_one_view.api.agent.utils import make_report_url, verify_signed_report_name
from doova_one_view.api.middleware import RateLimiter
from odoo_app.models import AppUser, Tenant
from odoo_app.models.agent import ChatSession
from odoo_app.models.user_tenant_access import UserTenantAccess


def _tenant(name):
    return Tenant.objects.create(
        name=name, odoo_url=f"http://{name}.example.com", odoo_database=name,
        api_key_encrypted=b"k", is_active=True,
    )


def _user(email, superuser=False):
    return AppUser.objects.create(email=email, password_hash="x", is_superuser=superuser)


class AgentScopeTests(TestCase):
    def setUp(self):
        set_authorized_tenant_ids(None)
        self.t1, self.t2 = _tenant("alpha"), _tenant("beta")
        self.alice = _user("alice@example.com")
        self.bob = _user("bob@example.com")
        UserTenantAccess.objects.create(user=self.alice, tenant=self.t1)
        UserTenantAccess.objects.create(user=self.bob, tenant=self.t2)

    def tearDown(self):
        set_authorized_tenant_ids(None)

    def test_user_gets_only_their_tenants_when_none_requested(self):
        scope, accessible = access.resolve_scope_sync(self.alice, None)
        self.assertEqual(scope, [str(self.t1.id)])
        self.assertEqual(accessible, {str(self.t1.id)})

    def test_requesting_another_tenant_is_forbidden(self):
        with self.assertRaises(HTTPException) as ctx:
            access.resolve_scope_sync(self.alice, [str(self.t2.id)])
        self.assertEqual(ctx.exception.status_code, 403)

    def test_mixing_allowed_and_foreign_tenant_is_forbidden(self):
        with self.assertRaises(HTTPException) as ctx:
            access.resolve_scope_sync(self.alice, [str(self.t1.id), str(self.t2.id)])
        self.assertEqual(ctx.exception.status_code, 403)

    def test_user_without_tenant_access_is_forbidden(self):
        nobody = _user("nobody@example.com")
        with self.assertRaises(HTTPException) as ctx:
            access.resolve_scope_sync(nobody, None)
        self.assertEqual(ctx.exception.status_code, 403)

    def test_superuser_may_use_any_tenant(self):
        root = _user("root@example.com", superuser=True)
        scope, _ = access.resolve_scope_sync(root, [str(self.t2.id)])
        self.assertEqual(scope, [str(self.t2.id)])
        scope, _ = access.resolve_scope_sync(root, None)
        self.assertEqual(set(scope), {str(self.t1.id), str(self.t2.id)})

    def test_tenant_requested_by_name_is_also_checked(self):
        # normalize_tenant_ids resolves names to ids; the check must apply after that.
        with self.assertRaises(HTTPException):
            access.resolve_scope_sync(self.alice, ["beta"])

    def test_normalize_is_clipped_to_the_authorized_set(self):
        access.resolve_scope_sync(self.alice, None)
        # a tool argument (or prompt) naming the other tenant gets only alice's tenant
        self.assertEqual(normalize_tenant_ids([str(self.t2.id)]), [str(self.t1.id)])
        self.assertEqual(normalize_tenant_ids([str(self.t2.id), str(self.t1.id)]), [str(self.t1.id)])

    def test_empty_means_all_of_my_tenants_not_every_tenant(self):
        access.resolve_scope_sync(self.alice, None)
        self.assertEqual(normalize_tenant_ids(None), [str(self.t1.id)])
        self.assertEqual(normalize_tenant_ids([]), [str(self.t1.id)])
        sql, params = build_tenant_filter_sql(tenant_ids=None)
        self.assertIn("tenant_id", sql)
        self.assertEqual(list(params.values()), [str(self.t1.id)])

    def test_without_a_scope_behaviour_is_unchanged(self):
        # KPI, scripts and tests do not set a scope: nothing is clipped.
        self.assertIsNone(get_authorized_tenant_ids())
        self.assertEqual(
            sorted(normalize_tenant_ids([str(self.t1.id), str(self.t2.id)])),
            sorted([str(self.t1.id), str(self.t2.id)]),
        )
        self.assertEqual(normalize_tenant_ids(None), [])

    def test_narrow_scope_drops_tenants_the_user_lost_access_to(self):
        _, accessible = access.resolve_scope_sync(self.alice, None)
        scope = access.narrow_scope(accessible, [str(self.t2.id)])
        self.assertEqual(scope, [str(self.t1.id)])

    def test_job_wrapper_passes_the_jobs_own_tenant_ids_keyword_through(self):
        # Regression: alert_job/report_job call run_in_scope(tenant_ids, agent.run, prompt, tenant_ids=...).
        seen = {}

        def agent_run(prompt, tenant_ids=None, company_ids=None):
            seen["prompt"], seen["tenant_ids"] = prompt, tenant_ids
            seen["visible"] = normalize_tenant_ids([str(self.t1.id), str(self.t2.id)])
            return "ok"

        result = run_in_scope([str(self.t2.id)], agent_run, "check", tenant_ids=[str(self.t2.id)], company_ids=[])
        self.assertEqual(result, "ok")
        self.assertEqual(seen["tenant_ids"], [str(self.t2.id)])
        self.assertEqual(seen["visible"], [str(self.t2.id)])

    def test_job_runs_only_with_its_schedule_tenants(self):
        seen = {}

        def work():
            seen["tenants"] = normalize_tenant_ids([str(self.t1.id), str(self.t2.id)])

        run_in_scope([str(self.t2.id)], work)
        self.assertEqual(seen["tenants"], [str(self.t2.id)])


class SessionOwnershipTests(TestCase):
    def setUp(self):
        self.sm = SessionManager()
        self.t1, self.t2 = _tenant("alpha"), _tenant("beta")
        self.alice, self.bob = _user("alice@example.com"), _user("bob@example.com")
        UserTenantAccess.objects.create(user=self.alice, tenant=self.t1)
        UserTenantAccess.objects.create(user=self.bob, tenant=self.t2)
        self.acc_a = {str(self.t1.id)}
        self.acc_b = {str(self.t2.id)}

    def _create(self, sid="s-1"):
        return self.sm.get_or_create_session(sid, str(self.t1.id), None, self.alice, self.acc_a)

    def test_new_session_is_owned_by_the_creator(self):
        s = self._create()
        self.assertEqual(s.user_id, self.alice.id)

    def test_another_user_cannot_attach_to_the_session(self):
        self._create()
        with self.assertRaises(SessionAccessDenied):
            self.sm.get_or_create_session("s-1", str(self.t2.id), None, self.bob, self.acc_b)

    def test_another_user_cannot_read_by_id(self):
        self._create()
        with self.assertRaises(SessionAccessDenied):
            self.sm.get_session_for_user("s-1", self.bob, self.acc_b)

    def test_missing_session_is_does_not_exist(self):
        with self.assertRaises(ChatSession.DoesNotExist):
            self.sm.get_session_for_user("nope", self.alice, self.acc_a)

    def test_listing_only_shows_my_sessions(self):
        self._create("a-1")
        self.sm.get_or_create_session("b-1", str(self.t2.id), None, self.bob, self.acc_b)
        mine = {s.session_id for s in self.sm.get_sessions(None, self.alice, self.acc_a)}
        self.assertEqual(mine, {"a-1"})
        # without a user (internal callers) nothing changes
        self.assertEqual({s.session_id for s in self.sm.get_sessions()}, {"a-1", "b-1"})

    def test_listing_with_a_foreign_tenant_filter_is_empty(self):
        self._create("a-1")
        self.assertEqual(list(self.sm.get_sessions(str(self.t1.id), self.bob, self.acc_b)), [])

    def test_legacy_session_is_open_to_its_tenant_and_then_claimed(self):
        ChatSession.objects.create(session_id="old", tenant_id=str(self.t1.id))  # no owner
        got = self.sm.get_session_for_user("old", self.alice, self.acc_a)
        self.assertEqual(got.user_id, self.alice.id)
        # once claimed it is private to alice
        colleague = _user("carol@example.com")
        UserTenantAccess.objects.create(user=colleague, tenant=self.t1)
        with self.assertRaises(SessionAccessDenied):
            self.sm.get_session_for_user("old", colleague, self.acc_a)

    def test_legacy_session_is_closed_to_other_tenants(self):
        ChatSession.objects.create(session_id="old", tenant_id=str(self.t1.id))
        with self.assertRaises(SessionAccessDenied):
            self.sm.get_session_for_user("old", self.bob, self.acc_b)

    def test_legacy_session_without_tenant_is_superuser_only(self):
        ChatSession.objects.create(session_id="old", tenant_id="default")
        with self.assertRaises(SessionAccessDenied):
            self.sm.get_session_for_user("old", self.alice, self.acc_a)
        root = _user("root@example.com", superuser=True)
        self.assertEqual(self.sm.get_session_for_user("old", root, set()).user_id, root.id)


class SignedReportLinkTests(TestCase):
    def test_link_carries_a_verifiable_signature(self):
        url = make_report_url("sales_report_Acme_2026.pdf")
        token = url.rsplit("/", 1)[1]
        self.assertTrue(token.endswith("~sales_report_Acme_2026.pdf"))
        self.assertEqual(verify_signed_report_name(token), "sales_report_Acme_2026.pdf")

    def test_relative_report_path_is_signed_too(self):
        # Regression: POST /report returned the unsigned relative path, so the link needed a login.
        from doova_one_view.api.agent.utils import make_report_path

        path = make_report_path("sales_report_Acme_2026.pdf")
        self.assertTrue(path.startswith("/financial-advisor/reports/"))
        token = path.rsplit("/", 1)[1]
        self.assertEqual(verify_signed_report_name(token), "sales_report_Acme_2026.pdf")
        self.assertEqual(token, make_report_url("sales_report_Acme_2026.pdf").rsplit("/", 1)[1])

    def test_report_tools_no_longer_build_unsigned_paths(self):
        from pathlib import Path
        import doova_one_view.api.agent.tools_refactored.reporting as reporting

        folder = Path(reporting.__file__).resolve().parent
        for name in ("generate_report_tool.py", "_pdf_renderer.py"):
            self.assertNotIn('f"/financial-advisor/reports/{filename}"', (folder / name).read_text(encoding="utf-8"))

    def test_plain_file_name_is_not_a_valid_token(self):
        self.assertIsNone(verify_signed_report_name("sales_report_Acme_2026.pdf"))

    def test_tampered_name_or_signature_is_rejected(self):
        token = make_report_url("a.pdf").rsplit("/", 1)[1]
        sig, _, _ = token.partition("~")
        self.assertIsNone(verify_signed_report_name(f"{sig}~b.pdf"))
        self.assertIsNone(verify_signed_report_name(f"{'0' * 32}~a.pdf"))

    def test_signature_changes_with_the_secret(self):
        from django.test import override_settings
        before = make_report_url("a.pdf")
        with override_settings(SECRET_KEY="another-secret-key-for-test-only-0123456789"):
            after = make_report_url("a.pdf")
            self.assertNotEqual(before, after)
            self.assertIsNone(verify_signed_report_name(before.rsplit("/", 1)[1]))

    def test_path_traversal_in_the_name_is_stripped(self):
        url = make_report_url("../../etc/passwd")
        self.assertTrue(url.endswith("~passwd"))
        self.assertNotIn("..", url)


class RateLimiterBoundsTests(TestCase):
    def test_idle_keys_are_pruned_when_the_table_is_full(self):
        limiter = RateLimiter(requests_per_minute=5)
        limiter.MAX_KEYS = 50
        for i in range(60):
            limiter.is_allowed(f"ip:{i}")
        # all of them are inside the window, so none is dropped yet
        self.assertGreaterEqual(len(limiter.requests), 50)
        for timestamps in limiter.requests.values():
            timestamps[:] = [t - 120 for t in timestamps]  # age everything past the window
        limiter.is_allowed("ip:new")
        self.assertLessEqual(len(limiter.requests), 2)

    def test_limit_still_applies_per_key(self):
        limiter = RateLimiter(requests_per_minute=2)
        self.assertTrue(limiter.is_allowed("k")[0])
        self.assertTrue(limiter.is_allowed("k")[0])
        self.assertFalse(limiter.is_allowed("k")[0])
        self.assertTrue(limiter.is_allowed("other")[0])

    def test_middleware_key_ignores_the_tenant_header(self):
        import asyncio
        from types import SimpleNamespace
        from doova_one_view.api import middleware as mw

        mw.agent_chat_rate_limiter.reset()
        mw.agent_chat_rate_limiter.rpm = 2

        class _Resp:
            headers: dict = {}

        async def call_next(_request):
            return _Resp()

        def make_request(tenant_header):
            return SimpleNamespace(
                url=SimpleNamespace(path="/api/v1/financial-advisor/chat"),
                method="POST",
                headers={"Authorization": "Bearer token-abcdef-0123456789", "X-Tenant-Id": tenant_header},
                client=SimpleNamespace(host="10.0.0.1"),
            )

        try:
            statuses = []
            for i in range(4):
                resp = asyncio.run(mw.rate_limit_middleware(make_request(f"tenant-{i}"), call_next))
                statuses.append(getattr(resp, "status_code", 200))
            # changing X-Tenant-Id must not give a fresh allowance
            self.assertEqual(statuses, [200, 200, 429, 429])
        finally:
            mw.agent_chat_rate_limiter.rpm = 120
            mw.agent_chat_rate_limiter.reset()
