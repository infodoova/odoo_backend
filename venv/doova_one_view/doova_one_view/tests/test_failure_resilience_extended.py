# doova_one_view/tests/test_failure_resilience_extended.py

import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "doova_one_view.settings")
django.setup()

import unittest
from unittest.mock import patch, MagicMock
from doova_one_view.api.agent.router import RouterNode
from doova_one_view.api.agent.session_manager import SessionManager
from doova_one_view.api.agent.utils import parse_graph_data_from_text

class TestFailureResilienceExtended(unittest.TestCase):

    def setUp(self):
        with patch("langchain_anthropic.ChatAnthropic"):
            self.router = RouterNode()
        self.session_mgr = SessionManager()

    def test_session_manager_missing_session_resilience(self):
        """Ensure SessionManager returns default values safely when session_id does not exist."""
        non_existent_id = "non_existent_session_999"
        messages = list(self.session_mgr.get_messages(non_existent_id))
        self.assertEqual(messages, [])

    @patch("odoo_app.models.agent.ChatSession.objects")
    @patch("odoo_app.models.agent.ChatMessage.objects")
    def test_session_manager_corrupted_data_recovery(self, mock_msg_objs, mock_sess_objs):
        """Ensure SessionManager clear and reset methods handle edge cases cleanly."""
        sess_id = "test_resilience_session"
        mock_sess = MagicMock()
        mock_sess_objs.get_or_create.return_value = (mock_sess, False)
        
        session = self.session_mgr.get_or_create_session(sess_id, "tenant_123")
        self.assertEqual(session, mock_sess)

        self.session_mgr.delete_session(sess_id)
        mock_sess_objs.filter.assert_called_with(session_id=sess_id)

    def test_graph_parser_with_noise_and_extreme_values(self):
        """Verify parse_graph_data_from_text handles noise, large suffixes (B, M, K), and negative values."""
        text_with_metrics = """
        Here is the monthly breakdown:
        Jan 2026    $1.5B
        Feb 2026    $500.0M
        Mar 2026    -$250K
        """
        graph = parse_graph_data_from_text(text_with_metrics)
        self.assertIsNotNone(graph)
        self.assertEqual(len(graph), 3)
        self.assertEqual(graph[0]["value"], 1500000000.0)
        self.assertEqual(graph[1]["value"], 500000000.0)
        self.assertEqual(graph[2]["value"], -250000.0)

    @patch("langchain_core.runnables.base.RunnableSequence.invoke")
    def test_router_handles_unexpected_non_string_llm_output(self, mock_invoke):
        """Ensure RouterNode doesn't crash if LLM returns unexpected object or structure."""
        mock_response = MagicMock()
        mock_response.content = "   EXECUTE  "
        mock_invoke.return_value = mock_response

        decision = self.router.classify("Tell me about revenue")
        self.assertEqual(decision, "EXECUTE")

if __name__ == "__main__":
    unittest.main()
