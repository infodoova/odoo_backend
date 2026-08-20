"""
Unit tests for the Strategic Advisor Tool (Executor–Advisor pattern).
Validates feature toggling, safety guardrails, graceful error handling,
and SQL correction integration.
"""

from unittest.mock import MagicMock, patch
from django.test import TestCase
from langchain_core.messages import AIMessage

from doova_one_view.api.agent.config import AgentConfig
from doova_one_view.api.agent.advisor_tool import (
    StrategicAdvisorService,
    consult_strategic_advisor_tool,
)
from doova_one_view.api.agent.sql_agent import _attempt_sql_correction


class AdvisorToolTestCase(TestCase):
    """Tests for the Strategic Advisor Service and LangChain tool wrapper."""

    def setUp(self):
        # Reset any cached LLM instance between tests
        StrategicAdvisorService._advisor_llm = None

    def test_disabled_by_default_feature_flag(self):
        """When ENABLE_ADVISOR_TOOL is False, advisor returns disabled status without calling LLM."""
        with patch.object(AgentConfig, "ENABLE_ADVISOR_TOOL", False):
            sql_res = StrategicAdvisorService.advise_sql(
                question="Calculate net revenue",
                schema_context="table fact_sales_orders",
            )
            self.assertFalse(sql_res["advised"])
            self.assertIn("disabled", sql_res["reason"].lower())

            strat_res = StrategicAdvisorService.advise_financial_strategy(
                question="Analyze cash runway",
                metrics_data={"cash_balance": 50000},
            )
            self.assertFalse(strat_res["advised"])
            self.assertIn("disabled", strat_res["reason"].lower())

            tool_msg = consult_strategic_advisor_tool(
                problem_type="sql_planning",
                question="Calculate net revenue",
            )
            self.assertIn("disabled", tool_msg.lower())

    def test_advisor_sql_planning_success(self):
        """When ENABLE_ADVISOR_TOOL is True, advise_sql calls LLM and returns advice."""
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = AIMessage(content="SELECT * FROM fact_sales_orders WHERE tenant_id = '123';")

        with patch.object(AgentConfig, "ENABLE_ADVISOR_TOOL", True), \
             patch.object(StrategicAdvisorService, "get_llm", return_value=mock_llm):
            res = StrategicAdvisorService.advise_sql(
                question="Show multi-currency sales",
                schema_context="fact_sales_orders schema",
            )
            self.assertTrue(res["advised"])
            self.assertIn("SELECT * FROM fact_sales_orders", res["guidance"])
            self.assertIn("duration_ms", res)
            mock_llm.invoke.assert_called_once()

    def test_advisor_financial_strategy_success(self):
        """When ENABLE_ADVISOR_TOOL is True, advise_financial_strategy returns strategic analysis."""
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = AIMessage(
            content="### Executive Assessment\nWorking capital has tightened by 15% due to delayed receivables."
        )

        with patch.object(AgentConfig, "ENABLE_ADVISOR_TOOL", True), \
             patch.object(StrategicAdvisorService, "get_llm", return_value=mock_llm):
            res = StrategicAdvisorService.advise_financial_strategy(
                question="Why is operating cash low?",
                metrics_data={"dso": 65, "dpo": 30},
                tenant_context={"currency": "USD"},
            )
            self.assertTrue(res["advised"])
            self.assertIn("Working capital has tightened", res["strategic_assessment"])
            mock_llm.invoke.assert_called_once()

    def test_advisor_graceful_error_handling(self):
        """If the LLM raises an exception, the advisor returns safe fallback without crashing."""
        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = RuntimeError("Anthropic API rate limit exceeded")

        with patch.object(AgentConfig, "ENABLE_ADVISOR_TOOL", True), \
             patch.object(StrategicAdvisorService, "get_llm", return_value=mock_llm):
            res = StrategicAdvisorService.advise_sql(
                question="Calculate net revenue",
                schema_context="schema",
            )
            self.assertFalse(res["advised"])
            self.assertIn("rate limit exceeded", res["error"])

    def test_sql_agent_model_tiering_on_retry(self):
        """When ENABLE_ADVISOR_TOOL is True, _attempt_sql_correction uses ADVISOR_MODEL."""
        mock_client = MagicMock()
        mock_msg = MagicMock()
        mock_msg.content = [MagicMock(text="```sql\nSELECT id FROM fact_sales_orders\n```")]
        mock_client.messages.create.return_value = mock_msg

        with patch.object(AgentConfig, "ENABLE_ADVISOR_TOOL", True), \
             patch.object(AgentConfig, "ADVISOR_MODEL", "claude-sonnet-5"):
            corrected = _attempt_sql_correction(
                client=mock_client,
                retry_prompt="Fix query",
                model="claude-haiku-4-5-20251001",
            )
            self.assertEqual(corrected, "SELECT id FROM fact_sales_orders")
            # Verify the create call targeted ADVISOR_MODEL
            call_kwargs = mock_client.messages.create.call_args[1]
            self.assertEqual(call_kwargs["model"], "claude-sonnet-5")
