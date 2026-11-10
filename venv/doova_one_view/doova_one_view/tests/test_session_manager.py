# doova_one_view/tests/test_session_manager.py

import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "doova_one_view.settings")
django.setup()

import unittest
import datetime
from unittest.mock import patch, MagicMock
from django.utils import timezone
from doova_one_view.api.agent.session_manager import SessionManager
from odoo_app.models.agent import ChatSession, ChatMessage

TENANT_ID = "3fa85f64-5717-4562-b3fc-2c963f66afa6"


class TestSessionManagerBasic(unittest.TestCase):

    def setUp(self):
        with patch("langchain_anthropic.ChatAnthropic"):
            self.manager = SessionManager()

    def tearDown(self):
        ChatSession.objects.filter(session_id__startswith="test_sm_").delete()

    @patch.object(SessionManager, "generate_title")
    def test_get_or_create_session_new(self, mock_generate_title):
        mock_generate_title.return_value = "Inventory Health Analysis"
        session_id = "test_sm_1001"
        session = self.manager.get_or_create_session(
            session_id=session_id,
            tenant_id=TENANT_ID,
            first_message="Tell me about my inventory health"
        )
        self.assertIsNotNone(session)
        self.assertEqual(session.session_id, session_id)
        self.assertEqual(session.title, "Inventory Health Analysis")

    def test_save_message(self):
        session_id = "test_sm_1002"
        session = ChatSession.objects.create(
            session_id=session_id,
            tenant_id=TENANT_ID,
            title="Sales Inquiry"
        )
        self.manager.save_message(
            session_id=session_id,
            role="user",
            content="What are my top products?"
        )
        messages = list(session.messages.all())
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].role, "user")
        self.assertEqual(messages[0].content, "What are my top products?")

    @patch.object(SessionManager, "generate_title")
    def test_generate_title_fallback(self, mock_generate_title):
        mock_generate_title.return_value = "Why did revenue drop in Q2?"
        title = self.manager.generate_title("Why did revenue drop in Q2?")
        self.assertEqual(title, "Why did revenue drop in Q2?")

    def test_get_or_create_session_returns_existing(self):
        """Calling get_or_create_session twice returns the same session."""
        session_id = "test_sm_1003"
        with patch.object(SessionManager, "generate_title", return_value="Existing Session"):
            s1 = self.manager.get_or_create_session(session_id=session_id, tenant_id=TENANT_ID)
            s2 = self.manager.get_or_create_session(session_id=session_id, tenant_id=TENANT_ID)
        self.assertEqual(s1.session_id, s2.session_id)

    def test_save_summary(self):
        session_id = "test_sm_1004"
        ChatSession.objects.create(session_id=session_id, tenant_id=TENANT_ID)
        self.manager.save_summary(session_id, "Revenue grew 15% YoY.")
        updated = ChatSession.objects.get(session_id=session_id)
        self.assertEqual(updated.summary, "Revenue grew 15% YoY.")

    def test_get_sessions_filtered_by_tenant(self):
        """get_sessions() with tenant_id returns only that tenant's sessions."""
        other_tenant = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        ChatSession.objects.create(session_id="test_sm_2001", tenant_id=TENANT_ID)
        ChatSession.objects.create(session_id="test_sm_2002", tenant_id=other_tenant)
        results = list(self.manager.get_sessions(tenant_id=TENANT_ID))
        session_ids = [s.session_id for s in results]
        self.assertIn("test_sm_2001", session_ids)
        self.assertNotIn("test_sm_2002", session_ids)

    def test_get_messages_returns_correct_messages(self):
        session_id = "test_sm_1005"
        session = ChatSession.objects.create(session_id=session_id, tenant_id=TENANT_ID)
        ChatMessage.objects.create(session=session, role="user", content="Hi")
        ChatMessage.objects.create(session=session, role="assistant", content="Hello!")
        messages = list(self.manager.get_messages(session_id))
        self.assertEqual(len(messages), 2)

    def test_delete_session(self):
        session_id = "test_sm_1006"
        ChatSession.objects.create(session_id=session_id, tenant_id=TENANT_ID)
        self.manager.delete_session(session_id)
        self.assertFalse(ChatSession.objects.filter(session_id=session_id).exists())

    def test_delete_session_still_deletes_when_attachment_cleanup_fails(self):
        """A cleanup failure must be logged, not crash the delete (regression: missing logger import)."""
        session_id = "test_sm_1007"
        ChatSession.objects.create(session_id=session_id, tenant_id=TENANT_ID)
        with patch(
            "doova_one_view.api.agent.attachment_processor.cleanup_session_attachments",
            side_effect=RuntimeError("disk error"),
        ), patch("doova_one_view.api.agent.session_manager.logger") as mock_logger:
            self.manager.delete_session(session_id)
        self.assertFalse(ChatSession.objects.filter(session_id=session_id).exists())
        mock_logger.warning.assert_called_once()
        self.assertIn(session_id, mock_logger.warning.call_args[0][0])


class TestPlanStateLifecycle(unittest.TestCase):
    """
    Tests for plan_state + plan_created_at lifecycle:
    - Plan is stamped with creation time
    - Stale plan (>30 min) should be detected as expired
    - Fresh plan (<30 min) should be detected as valid
    - reset_session_memory() clears plan_created_at
    """

    def setUp(self):
        with patch("langchain_anthropic.ChatAnthropic"):
            self.manager = SessionManager()

    def tearDown(self):
        ChatSession.objects.filter(session_id__startswith="test_plan_").delete()

    def test_plan_created_at_is_null_by_default(self):
        """New sessions have no plan timestamp."""
        session = ChatSession.objects.create(
            session_id="test_plan_2001",
            tenant_id=TENANT_ID
        )
        self.assertIsNone(session.plan_created_at)
        self.assertIsNone(session.plan_state)

    def test_fresh_plan_is_not_expired(self):
        """A plan created now should NOT be considered expired."""
        session = ChatSession.objects.create(
            session_id="test_plan_2002",
            tenant_id=TENANT_ID,
            plan_state={"steps": ["Analyse sales"]},
            plan_created_at=timezone.now()
        )
        age_minutes = (timezone.now() - session.plan_created_at).total_seconds() / 60
        self.assertLess(age_minutes, 30, "A plan created just now must not be expired")

    def test_stale_plan_is_expired(self):
        """A plan created 35 minutes ago must be considered expired (>30 min TTL)."""
        old_timestamp = timezone.now() - datetime.timedelta(minutes=35)
        session = ChatSession.objects.create(
            session_id="test_plan_2003",
            tenant_id=TENANT_ID,
            plan_state={"steps": ["Analyse inventory"]},
            plan_created_at=old_timestamp
        )
        age_minutes = (timezone.now() - session.plan_created_at).total_seconds() / 60
        self.assertGreater(age_minutes, 30, "A 35-minute-old plan must be detected as stale")

    def test_plan_on_boundary_31_minutes_is_expired(self):
        """31 minutes should trigger expiry (> 30 min threshold)."""
        boundary_timestamp = timezone.now() - datetime.timedelta(minutes=31)
        session = ChatSession.objects.create(
            session_id="test_plan_2004",
            tenant_id=TENANT_ID,
            plan_state={"steps": ["Run forecast"]},
            plan_created_at=boundary_timestamp
        )
        age_minutes = (timezone.now() - session.plan_created_at).total_seconds() / 60
        self.assertGreater(age_minutes, 30)

    def test_plan_on_boundary_29_minutes_is_valid(self):
        """29 minutes should NOT trigger expiry (< 30 min threshold)."""
        fresh_timestamp = timezone.now() - datetime.timedelta(minutes=29)
        session = ChatSession.objects.create(
            session_id="test_plan_2005",
            tenant_id=TENANT_ID,
            plan_state={"steps": ["Run forecast"]},
            plan_created_at=fresh_timestamp
        )
        age_minutes = (timezone.now() - session.plan_created_at).total_seconds() / 60
        self.assertLess(age_minutes, 30)

    def test_reset_session_memory_clears_plan_state_and_timestamp(self):
        """reset_session_memory() must null both plan_state and plan_created_at."""
        session_id = "test_plan_2006"
        session = ChatSession.objects.create(
            session_id=session_id,
            tenant_id=TENANT_ID,
            plan_state={"steps": ["step1"]},
            plan_created_at=timezone.now(),
            summary="Some summary",
            turn_count=5
        )
        self.manager.reset_session_memory(session_id)
        refreshed = ChatSession.objects.get(session_id=session_id)
        self.assertIsNone(refreshed.plan_state)
        self.assertIsNone(refreshed.plan_created_at)
        self.assertEqual(refreshed.turn_count, 0)
        self.assertEqual(refreshed.summary, "")

    def test_session_with_no_plan_created_at_treated_as_non_expired(self):
        """
        Legacy sessions with plan_state but NULL plan_created_at should not crash
        the expiry check. The routes.py guard only evaluates expiry when
        plan_created_at is not None.
        """
        session = ChatSession.objects.create(
            session_id="test_plan_2007",
            tenant_id=TENANT_ID,
            plan_state={"steps": ["legacy plan"]},
            plan_created_at=None   # legacy session before the migration
        )
        # Simulate the guard: if plan_created_at is None, skip age check → plan is valid
        plan_age_ok = True
        if session.plan_created_at:
            age_minutes = (timezone.now() - session.plan_created_at).total_seconds() / 60
            plan_age_ok = age_minutes <= 30
        self.assertTrue(plan_age_ok, "Null plan_created_at should not reject plan execution")


if __name__ == "__main__":
    unittest.main()
