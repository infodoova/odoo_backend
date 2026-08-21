"""
Unit tests for the Direct Anthropic Web Search Agent and Routes Integration.
Tests tool schema conversion, native web_search tool list construction,
citation extraction, multi-turn loop, and chat endpoint flag handling.
"""

from unittest.mock import MagicMock, patch
from django.test import TestCase
from langchain_core.tools import tool

from doova_one_view.api.agent.config import AgentConfig
from doova_one_view.api.agent.web_search_agent import (
    WebSearchAgent,
    convert_langchain_tool_to_anthropic,
)
from doova_one_view.api.agent.routes import ChatRequest, make_chat_response


@tool
def sample_business_tool(metric: str, days: int = 30) -> str:
    """Sample calculation tool for testing schema conversion."""
    return f"Calculated {metric} for {days} days"


class WebSearchAgentTestCase(TestCase):
    """Unit tests for WebSearchAgent and schema conversion."""

    def test_convert_langchain_tool_to_anthropic(self):
        """Converts LangChain tool to valid Anthropic tool schema."""
        converted = convert_langchain_tool_to_anthropic(sample_business_tool)
        self.assertEqual(converted["name"], "sample_business_tool")
        self.assertIn("Sample calculation tool", converted["description"])
        self.assertEqual(converted["input_schema"]["type"], "object")
        self.assertIn("metric", converted["input_schema"]["properties"])
        self.assertIn("days", converted["input_schema"]["properties"])

    def test_web_search_agent_tool_list_construction(self):
        """WebSearchAgent builds tool list containing native web_search + internal tools."""
        with patch.object(AgentConfig, "WEB_SEARCH_TOOL_VERSION", "web_search_20250305"), \
             patch.object(AgentConfig, "WEB_SEARCH_MAX_USES", 7), \
             patch.object(AgentConfig, "WEB_SEARCH_DEFAULT_COUNTRY", "CM"):
            agent = WebSearchAgent()
            tools = agent._anthropic_tools

            # Verify native server tool is present
            server_tool = tools[0]
            self.assertEqual(server_tool["type"], "web_search_20250305")
            self.assertEqual(server_tool["name"], "web_search")
            self.assertEqual(server_tool["max_uses"], 7)
            self.assertEqual(server_tool["user_location"]["country"], "CM")

            # Verify internal business tools are also present
            tool_names = [t.get("name") for t in tools]
            self.assertIn("calculate_pnl", tool_names)
            self.assertIn("sales_summary", tool_names)
            self.assertIn("inventory_valuation", tool_names)

    def test_web_search_agent_execution_with_citations(self):
        """WebSearchAgent extracts text and citations from Anthropic API response."""
        mock_citation = MagicMock()
        mock_citation.url = "https://example.com/market-rates"
        mock_citation.title = "Central Bank CEMAC Rates"
        mock_citation.cited_text = "Policy rate set to 5.0% in 2026."

        mock_text_block = MagicMock()
        mock_text_block.type = "text"
        mock_text_block.text = "The BEAC interest rate is 5.0%."
        mock_text_block.citations = [mock_citation]

        mock_response = MagicMock()
        mock_response.stop_reason = "end_turn"
        mock_response.content = [mock_text_block]

        agent = WebSearchAgent()
        agent.client = MagicMock()
        agent.client.messages.create.return_value = mock_response

        answer, citations = agent.run(
            message="What is the BEAC interest rate?",
            tenant_id="test_tenant",
        )

        self.assertIn("The BEAC interest rate is 5.0%", answer)
        self.assertEqual(len(citations), 1)
        self.assertEqual(citations[0]["url"], "https://example.com/market-rates")
        self.assertEqual(citations[0]["title"], "Central Bank CEMAC Rates")
        self.assertIn("5.0%", citations[0]["cited_text"])

    def test_chat_request_schema_aliases(self):
        """ChatRequest parses webSearch and web_search correctly."""
        req1 = ChatRequest(text="Hello", webSearch=True)
        self.assertTrue(req1.web_search)

        req2 = ChatRequest(text="Hello", web_search=True)
        self.assertTrue(req2.web_search)

        req3 = ChatRequest(text="Hello")
        self.assertFalse(req3.web_search)

    def test_make_chat_response_includes_citations(self):
        """make_chat_response includes citations field when provided."""
        citations = [{"url": "https://reuters.com/xaf", "title": "Reuters Forex", "cited_text": "605.5"}]
        res = make_chat_response(
            answer="XAF rate is 605.5",
            mode="EXECUTE",
            session_id="test_sess",
            session_title="Forex Session",
            user_message="Rate today?",
            citations=citations,
        )
        self.assertEqual(res["citations"], citations)
        self.assertEqual(res["type"], "text")
