"""
HTTP-level checks of the agent router: who can call what, and whose data they get.

Runs the real FastAPI app with real JWTs against the temporary test database. No call
reaches the language model: every request here is stopped (or answered) before that point.
"""

import os
import tempfile
from pathlib import Path

from django.conf import settings
from django.test import TransactionTestCase, override_settings
from fastapi.testclient import TestClient
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

from doova_one_view.api.agent.utils import make_report_url
from odoo_app.models import AppUser, Tenant
from odoo_app.models.agent import ChatMessage, ChatSession
from odoo_app.models.rbac import Permission, Role, UserRole
from odoo_app.models.user_tenant_access import UserTenantAccess


def _tenant(name):
    return Tenant.objects.create(
        name=name, odoo_url=f"http://{name}.example.com", odoo_database=name,
        api_key_encrypted=b"k", is_active=True,
    )


class AgentEndpointSecurityTests(TransactionTestCase):
    def setUp(self):
        from doova_one_view.api.app import app

        self.client = TestClient(app)
        perm, _ = Permission.objects.get_or_create(codename="use_agent")
        role = Role.objects.create(name="agent-user")
        role.permissions.add(perm)

        self.t1, self.t2 = _tenant("alpha"), _tenant("beta")
        self.alice = AppUser.objects.create(email="alice@example.com", password_hash="x")
        self.bob = AppUser.objects.create(email="bob@example.com", password_hash="x")
        self.no_perm = AppUser.objects.create(email="np@example.com", password_hash="x")
        for user, tenant in ((self.alice, self.t1), (self.bob, self.t2)):
            UserRole.objects.create(user=user, role=role)
            UserTenantAccess.objects.create(user=user, tenant=tenant)

        self.sess_a = ChatSession.objects.create(session_id="sess-a", tenant_id=str(self.t1.id), user_id=self.alice.id)
        self.sess_b = ChatSession.objects.create(session_id="sess-b", tenant_id=str(self.t2.id), user_id=self.bob.id)
        ChatMessage.objects.create(session=self.sess_a, role="user", content="alice question")
        ChatMessage.objects.create(session=self.sess_b, role="user", content="bob secret question")

    def _auth(self, user):
        return {"Authorization": f"Bearer {AccessToken.for_user(user)}"}

    BASE = "/financial-advisor"

    # ── sessions ──────────────────────────────────────────────────────────────

    def test_session_list_contains_only_my_sessions(self):
        r = self.client.get(f"{self.BASE}/sessions", headers=self._auth(self.alice))
        self.assertEqual(r.status_code, 200)
        self.assertEqual({s["session_id"] for s in r.json()["sessions"]}, {"sess-a"})

    def test_session_list_for_a_foreign_tenant_is_forbidden(self):
        r = self.client.get(f"{self.BASE}/sessions", params={"tenant_id": str(self.t2.id)}, headers=self._auth(self.alice))
        self.assertEqual(r.status_code, 403)

    def test_cannot_read_someone_elses_messages(self):
        r = self.client.get(f"{self.BASE}/sessions/sess-b/messages", headers=self._auth(self.alice))
        self.assertEqual(r.status_code, 404)
        self.assertNotIn("bob secret", r.text)

    def test_cannot_read_someone_elses_session_details(self):
        r = self.client.get(f"{self.BASE}/sessions/sess-b", headers=self._auth(self.alice))
        self.assertEqual(r.status_code, 404)

    def test_cannot_delete_someone_elses_session(self):
        r = self.client.delete(f"{self.BASE}/sessions/sess-b", headers=self._auth(self.alice))
        self.assertEqual(r.status_code, 404)
        self.assertTrue(ChatSession.objects.filter(session_id="sess-b").exists())

    def test_reading_a_missing_session_does_not_create_it(self):
        r = self.client.get(f"{self.BASE}/sessions/never-existed", headers=self._auth(self.alice))
        self.assertEqual(r.status_code, 404)
        self.assertFalse(ChatSession.objects.filter(session_id="never-existed").exists())

    def test_owner_can_read_and_delete_their_session(self):
        r = self.client.get(f"{self.BASE}/sessions/sess-a/messages", headers=self._auth(self.alice))
        self.assertEqual(r.status_code, 200)
        self.assertEqual([m["content"] for m in r.json()["messages"]], ["alice question"])
        r = self.client.delete(f"{self.BASE}/sessions/sess-a", headers=self._auth(self.alice))
        self.assertEqual(r.status_code, 200)
        self.assertFalse(ChatSession.objects.filter(session_id="sess-a").exists())

    # ── chat scope ────────────────────────────────────────────────────────────

    def test_chat_for_a_foreign_tenant_is_forbidden_before_anything_runs(self):
        r = self.client.post(
            f"{self.BASE}/chat",
            json={"message": "show me revenue", "tenant_ids": [str(self.t2.id)], "session_id": "new"},
            headers=self._auth(self.alice),
        )
        self.assertEqual(r.status_code, 403)

    def test_chat_cannot_join_someone_elses_session(self):
        r = self.client.post(
            f"{self.BASE}/chat",
            json={"message": "hello there", "tenant_ids": [str(self.t1.id)], "session_id": "sess-b"},
            headers=self._auth(self.alice),
        )
        self.assertEqual(r.status_code, 404)
        self.assertEqual(ChatMessage.objects.filter(session_id="sess-b").count(), 1)

    def test_report_for_a_foreign_tenant_is_forbidden(self):
        r = self.client.post(
            f"{self.BASE}/report",
            json={"tenant_ids": [str(self.t2.id)], "report_type": "sales"},
            headers=self._auth(self.alice),
        )
        self.assertEqual(r.status_code, 403)

    def test_analysis_for_a_foreign_tenant_is_forbidden(self):
        r = self.client.post(
            f"{self.BASE}/analysis",
            json={"tenant_ids": [str(self.t2.id)], "focus_area": "Sales & Revenue"},
            headers=self._auth(self.alice),
        )
        self.assertEqual(r.status_code, 403)

    def test_user_without_the_permission_is_forbidden(self):
        UserTenantAccess.objects.create(user=self.no_perm, tenant=self.t1)
        r = self.client.get(f"{self.BASE}/sessions", headers=self._auth(self.no_perm))
        self.assertEqual(r.status_code, 403)

    def test_no_token_is_rejected(self):
        self.assertEqual(self.client.get(f"{self.BASE}/sessions").status_code, 401)
        self.assertEqual(self.client.post(f"{self.BASE}/chat", json={"message": "hi"}).status_code, 401)


class ReportDownloadTests(TransactionTestCase):
    def setUp(self):
        from doova_one_view.api.app import app

        self.client = TestClient(app)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.name = "sales_report_Acme_2026_20261113_100000.pdf"
        (Path(self.tmp.name) / self.name).write_bytes(b"%PDF-1.4 test")
        self.user = AppUser.objects.create(email="alice@example.com", password_hash="x")
        self.base = "/financial-advisor/reports"

    def _get(self, token, **kwargs):
        with override_settings(REPORTS_DIR=Path(self.tmp.name)):
            return self.client.get(f"{self.base}/{token}", **kwargs)

    def test_signed_link_opens_without_login(self):
        token = make_report_url(self.name).rsplit("/", 1)[1]
        r = self._get(token)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.content, b"%PDF-1.4 test")

    def test_plain_file_name_needs_a_login(self):
        self.assertEqual(self._get(self.name).status_code, 401)

    def test_plain_file_name_works_for_a_signed_in_user(self):
        r = self._get(self.name, headers={"Authorization": f"Bearer {AccessToken.for_user(self.user)}"})
        self.assertEqual(r.status_code, 200)

    def test_forged_signature_is_not_accepted(self):
        self.assertEqual(self._get(f"{'0' * 32}~{self.name}").status_code, 401)

    def test_signature_for_another_file_does_not_unlock_this_one(self):
        other = make_report_url("other.pdf").rsplit("/", 1)[1].partition("~")[0]
        self.assertEqual(self._get(f"{other}~{self.name}").status_code, 401)

    def test_traversal_is_still_rejected_for_a_signed_link(self):
        token = make_report_url("../x.pdf").rsplit("/", 1)[1]  # name is reduced to x.pdf
        self.assertEqual(self._get(token).status_code, 404)

    def test_legacy_open_access_can_be_restored_by_environment(self):
        os.environ["AGENT_REPORTS_ALLOW_UNSIGNED"] = "true"
        self.addCleanup(os.environ.pop, "AGENT_REPORTS_ALLOW_UNSIGNED", None)
        self.assertEqual(self._get(self.name).status_code, 200)
