# doova_one_view/tests/test_resilience_failures.py

import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "doova_one_view.settings")
django.setup()

import unittest
from unittest.mock import patch
from doova_one_view.api.agent.router import RouterNode
from doova_one_view.api.agent.utils import parse_json_chart_from_text, parse_graph_data_from_text
from doova_one_view.api.agent.tools_refactored.common import get_tenant_profile_tool

class TestResilienceFailures(unittest.TestCase):

    def setUp(self):
        with patch("langchain_anthropic.ChatAnthropic"):
            self.router = RouterNode()

    @patch("langchain_core.runnables.base.RunnableSequence.invoke")
    def test_llm_timeout_resilience(self, mock_invoke):
        """Ensure Router falls back to EXECUTE on API Timeout without crashing."""
        mock_invoke.side_effect = TimeoutError("Anthropic API Connection Timeout")
        decision = self.router.classify("Show me sales for 2026")
        self.assertEqual(decision, "EXECUTE")

    @patch("langchain_core.runnables.base.RunnableSequence.invoke")
    def test_llm_rate_limit_resilience(self, mock_invoke):
        """Ensure Router handles HTTP 429 Rate Limit gracefully."""
        mock_invoke.side_effect = Exception("429 Too Many Requests: Rate limit exceeded")
        decision = self.router.classify("What is my top customer?")
        self.assertEqual(decision, "EXECUTE")

    def test_malformed_json_resilience(self):
        """Ensure JSON chart parser handles invalid / truncated JSON without crashing."""
        invalid_jsons = [
            "```json\n{type: 'chart', title: 'Unclosed\n```",
            "```json\n{\"type\": \"chart\", \"data\": [1, 2, 3, ]}\n```",
            "Not a json string at all",
            "",
            None
        ]
        for ij in invalid_jsons:
            result = parse_json_chart_from_text(ij)
            self.assertIsNone(result, f"Expected None for malformed JSON input: {ij}")

    def test_empty_graph_text_resilience(self):
        """Ensure graph data extractor returns None on empty or non-graph text."""
        self.assertIsNone(parse_graph_data_from_text(""))
        self.assertIsNone(parse_graph_data_from_text("Hello agent, how are you today?"))
        self.assertIsNone(parse_graph_data_from_text(None))

    @patch("doova_one_view.api.agent.tools_refactored.common.run_query")
    def test_tool_database_error_handling(self, mock_run_query):
        """Ensure tools handle database query failures safely by propagating or raising predictable exceptions."""
        mock_run_query.side_effect = Exception("PostgreSQL Connection Pool Exhausted")
        with self.assertRaises(Exception):
            get_tenant_profile_tool(tenant_id="default")

if __name__ == "__main__":
    unittest.main()
