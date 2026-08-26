# doova_one_view/tests/test_agent_behavior_eval.py

import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "doova_one_view.settings")
django.setup()

import unittest
from unittest.mock import patch, MagicMock
from doova_one_view.api.agent.classifier import IntentClassifier
from doova_one_view.api.agent.langchain_agent import DoovaLangChainAgent, ThinkingSafeChatAnthropic
from langchain_core.messages import AIMessage, HumanMessage

class TestAgentBehaviorEvaluation(unittest.TestCase):

    def setUp(self):
        with patch("anthropic.Anthropic"):
            self.classifier = IntentClassifier()

    def test_intent_understanding_and_tool_selection(self):
        """Scenario: User asks for sales summary; intent classifier identifies tool and extracts params."""
        mock_response = MagicMock()
        mock_response.content = [
            MagicMock(text='{"tool_name": "get_sales_summary_tool", "parameters": {"start_date": "2026-01-01", "end_date": "2026-01-31", "limit": 10}, "reasoning": "Sales query for Jan 2026"}')
        ]
        self.classifier.client.messages.create.return_value = mock_response

        res = self.classifier.classify_and_extract("Show me total sales for January 2026")
        self.assertEqual(res.get("tool_name"), "get_sales_summary_tool")
        self.assertEqual(res["parameters"].get("start_date"), "2026-01-01")
        self.assertEqual(res["parameters"].get("end_date"), "2026-01-31")

    def test_thinking_safe_chat_anthropic_strips_malformed_thinking(self):
        """Scenario: LLM message list contains incomplete thinking block missing 'thinking' text."""
        malformed_ai_msg = AIMessage(content=[
            {"type": "thinking", "signature": "abc"},  # missing 'thinking' text field
            {"type": "text", "text": "Here is the sales result."}
        ])
        cleaned = ThinkingSafeChatAnthropic._clean_messages([malformed_ai_msg])
        
        self.assertEqual(len(cleaned), 1)
        # Verify the malformed thinking block was stripped and only text block remains
        self.assertEqual(cleaned[0].content, [{"type": "text", "text": "Here is the sales result."}])

    def test_thinking_safe_chat_anthropic_preserves_valid_thinking(self):
        """Scenario: LLM message list contains valid thinking block with text and signature."""
        valid_ai_msg = AIMessage(content=[
            {"type": "thinking", "thinking": "Analyzing sales data...", "signature": "abc"},
            {"type": "text", "text": "Analysis complete."}
        ])
        cleaned = ThinkingSafeChatAnthropic._clean_messages([valid_ai_msg])
        self.assertEqual(len(cleaned[0].content), 2)
        self.assertEqual(cleaned[0].content[0]["thinking"], "Analyzing sales data...")

    def test_agent_history_formatting(self):
        """Scenario: Conversation history contains raw dicts and complex content blocks."""
        agent = DoovaLangChainAgent()
        history = [
            {"role": "user", "content": "What is my revenue?"},
            {"role": "assistant", "content": [{"type": "thinking", "thinking": "..." }, {"type": "text", "text": "Your revenue is $500,000."}]}
        ]
        formatted = agent._format_history(history)
        self.assertEqual(len(formatted), 2)
        self.assertIsInstance(formatted[0], HumanMessage)
        self.assertIsInstance(formatted[1], AIMessage)
        self.assertEqual(formatted[0].content, "What is my revenue?")
        self.assertEqual(formatted[1].content, "Your revenue is $500,000.")

    @patch("doova_one_view.api.agent.langchain_agent.AgentExecutor.invoke")
    @patch("doova_one_view.api.agent.utils.get_tenant_currency", return_value="USD")
    def test_agent_context_and_memory_summary_injection(self, mock_curr, mock_invoke):
        """Scenario: Memory summary is provided and formatted into system context before invoking LLM."""
        mock_invoke.return_value = {"output": "Based on prior context, total ARR is $1.2M."}
        
        agent = DoovaLangChainAgent()
        res = agent.run(
            message="What was our ARR again?",
            tenant_id="test-tenant-123",
            memory_summary="User asked about ARR previously; ARR was $1.2M in 2025."
        )
        
        self.assertIn("$1.2M", res)
        # Check invoke arguments
        called_args = mock_invoke.call_args[0][0]
        self.assertEqual(called_args["tenant_id"], "test-tenant-123")
        self.assertIn("PRIOR SESSION FACTS", called_args["memory_summary"])

if __name__ == "__main__":
    unittest.main()
