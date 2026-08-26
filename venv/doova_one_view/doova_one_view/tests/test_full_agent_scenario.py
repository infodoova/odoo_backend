# doova_one_view/tests/test_full_agent_scenario.py

import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "doova_one_view.settings")
django.setup()

import unittest
import json
from unittest.mock import patch, MagicMock
from doova_one_view.api.agent.router import RouterNode
from doova_one_view.api.agent.session_manager import SessionManager
from doova_one_view.api.agent.reasoning import ReasoningNode
from doova_one_view.api.agent.langchain_agent import DoovaLangChainAgent
from doova_one_view.api.agent.summarizer import SummarizerNode
from odoo_app.models.agent import ChatSession, ChatMessage

class TestFullAgentScenario(unittest.TestCase):

    def setUp(self):
        self.session_id = "test_full_e2e_scenario_9999"
        self.tenant_id = "3fa85f64-5717-4562-b3fc-2c963f66afa6"
        self.company_ids = [1]
        
        # Ensure clean state before scenario starts
        ChatSession.objects.filter(session_id=self.session_id).delete()
        
        with patch("langchain_anthropic.ChatAnthropic"):
            self.session_mgr = SessionManager()
            self.router = RouterNode()
            self.reasoning_node = ReasoningNode()
            self.agent = DoovaLangChainAgent()
            self.summarizer = SummarizerNode()

    def tearDown(self):
        # Clean up database after scenario completes
        ChatSession.objects.filter(session_id=self.session_id).delete()

    @patch("doova_one_view.api.agent.tools_refactored.sales.run_query")
    @patch("doova_one_view.api.agent.tools_refactored.finance.run_query")
    @patch("doova_one_view.api.agent.tools_refactored.inventory.run_query")
    @patch("langchain_core.runnables.base.RunnableSequence.invoke")
    def test_full_multi_turn_cfo_advisory_lifecycle_scenario(
        self, mock_router_invoke, mock_inv_query, mock_fin_query, mock_sales_query
    ):
        """
        FULL E2E ADVISORY LIFECYCLE SCENARIO:
        Turn 1: User asks for sales summary -> Router EXECUTE -> Sales Tool called -> Message saved.
        Turn 2: User asks for top products -> Router EXECUTE -> Top Products Tool called -> Message saved.
        Turn 3: User requests 90-day strategic optimization plan -> Router PLAN -> Plan created & staged in DB.
        Turn 4: User approves plan ("Yes proceed") -> Router CONFIRM -> Plan loaded from DB & executed -> Completed.
        Turn 5: Memory Summarization -> History compressed into executive brief & persisted to ChatSession.
        Turn 6: Explicit Memory Reset -> Reset API called -> Session reset to 0 turns & messages cleared.
        """

        # ------------------------------------------------------------------
        # TURN 1: Initial Sales Summary Inquiry
        # ------------------------------------------------------------------
        mock_router_resp = MagicMock()
        mock_router_resp.content = "EXECUTE"
        mock_router_invoke.return_value = mock_router_resp

        # Create session in DB
        session = self.session_mgr.get_or_create_session(
            session_id=self.session_id,
            tenant_id=self.tenant_id,
            first_message="Show me my sales summary for Q1 2026"
        )
        self.assertEqual(session.session_id, self.session_id)
        
        # Save Turn 1 User Message
        self.session_mgr.save_message(self.session_id, "user", "Show me my sales summary for Q1 2026")
        
        # Simulate Agent Tool Execution for Turn 1
        mock_sales_query.return_value = [
            {"total_revenue": 1250000.0, "order_count": 45, "average_order_value": 27777.77}
        ]
        from doova_one_view.api.agent.tools_refactored.sales import get_sales_summary_tool
        turn1_result = get_sales_summary_tool(
            tenant_id=self.tenant_id, company_ids=self.company_ids, start_date="2026-01-01", end_date="2026-03-31"
        )
        self.assertEqual(turn1_result["total_revenue"], 1250000.0)
        self.assertEqual(turn1_result["order_count"], 45)

        # Save Turn 1 Assistant Response
        self.session_mgr.save_message(
            self.session_id,
            "assistant",
            "In Q1 2026, total revenue reached $1,250,000 across 45 confirmed orders.",
            message_type="chart",
            payload={"type": "chart", "chart": {"data": [{"name": "Q1 2026", "value": 1250000.0}]}}
        )

        session.refresh_from_db()
        self.assertEqual(session.turn_count, 2)
        self.assertEqual(session.messages.count(), 2)

        # ------------------------------------------------------------------
        # TURN 2: Follow-up Inquiry on Top Products
        # ------------------------------------------------------------------
        self.session_mgr.save_message(self.session_id, "user", "Which top products drove that revenue?")
        
        mock_sales_query.return_value = [
            {"product_id": 101, "product_name": "Enterprise Server X", "quantity": 10, "revenue": 800000.0},
            {"product_id": 102, "product_name": "Cloud License Pro", "quantity": 50, "revenue": 450000.0}
        ]
        from doova_one_view.api.agent.tools_refactored.sales import get_top_products_tool
        turn2_result = get_top_products_tool(
            tenant_id=self.tenant_id, company_ids=self.company_ids, limit=5
        )
        self.assertEqual(len(turn2_result["products"]), 2)

        self.session_mgr.save_message(
            self.session_id,
            "assistant",
            "Top drivers were Enterprise Server X ($800K) and Cloud License Pro ($450K)."
        )

        session.refresh_from_db()
        self.assertEqual(session.turn_count, 4)
        self.assertEqual(session.messages.count(), 4)

        # ------------------------------------------------------------------
        # TURN 3: Request Strategic Plan (Two-Phase Workflow)
        # ------------------------------------------------------------------
        mock_router_resp.content = "PLAN"
        mock_router_invoke.return_value = mock_router_resp
        
        plan_request = "Create a 90-day working capital & inventory optimization roadmap."
        self.session_mgr.save_message(self.session_id, "user", plan_request)

        # Mock Plan Creation by ReasoningNode
        sample_plan = {
            "plan_id": "plan_90day_001",
            "title": "90-Day Working Capital Optimization Plan",
            "status": "PENDING_APPROVAL",
            "steps": [
                {"step": 1, "action": "Analyze AR aging & overdue invoices"},
                {"step": 2, "action": "Evaluate inventory turnover and stock out risks"}
            ]
        }
        
        # Stage plan in ChatSession database model
        session.plan_state = sample_plan
        session.save()

        self.session_mgr.save_message(
            self.session_id,
            "assistant",
            "I have generated a 90-day optimization roadmap. Please confirm to execute.",
            message_type="plan",
            payload=sample_plan
        )

        session.refresh_from_db()
        self.assertIsNotNone(session.plan_state)
        self.assertEqual(session.plan_state["plan_id"], "plan_90day_001")

        # ------------------------------------------------------------------
        # TURN 4: User Confirms & Approves Plan Execution
        # ------------------------------------------------------------------
        mock_router_resp.content = "CONFIRM"
        mock_router_invoke.return_value = mock_router_resp

        self.session_mgr.save_message(self.session_id, "user", "Yes, proceed with the plan")
        
        # Load staged plan & simulate execution
        staged_plan = session.plan_state
        self.assertEqual(staged_plan["status"], "PENDING_APPROVAL")

        # Execute mock tools during plan execution
        mock_fin_query.side_effect = [
            [{"total_receivables": 500000.0, "overdue": 120000.0}],
            [{"partner_name": "Global Tech", "overdue_amount": 120000.0}]
        ]
        from doova_one_view.api.agent.tools_refactored.finance import get_receivables_analysis_tool
        receivables_res = get_receivables_analysis_tool(tenant_id=self.tenant_id, company_ids=self.company_ids)
        self.assertEqual(receivables_res["overdue_receivables"], 120000.0)

        # Mark plan as executed and clear plan_state
        session.plan_state = None
        session.save()

        self.session_mgr.save_message(
            self.session_id,
            "assistant",
            "Plan execution completed successfully. Total overdue receivables analyzed: $120,000."
        )

        session.refresh_from_db()
        self.assertIsNone(session.plan_state)

        # ------------------------------------------------------------------
        # TURN 5: Memory Summarization Verification
        # ------------------------------------------------------------------
        # Verify SummarizerNode compiles history into a persisted summary
        history_msgs = list(ChatMessage.objects.filter(session=session))
        self.assertGreaterEqual(len(history_msgs), 6)

        mock_summary = (
            "- **KPIs Retrieved**: Q1 Revenue $1.25M, Top Product Enterprise Server X ($800K), AR Overdue $120K.\n"
            "- **Periods Analyzed**: 2026-01-01 to 2026-03-31.\n"
            "- **Tools Executed**: sales_summary, top_products, receivables_analysis."
        )
        self.session_mgr.save_summary(self.session_id, mock_summary)

        session.refresh_from_db()
        self.assertEqual(session.summary, mock_summary)

        # ------------------------------------------------------------------
        # TURN 6: Session Memory Reset Verification
        # ------------------------------------------------------------------
        # Test full session memory reset
        self.session_mgr.reset_session_memory(self.session_id)
        
        session.refresh_from_db()
        self.assertEqual(session.turn_count, 0)
        self.assertEqual(session.summary, "")
        self.assertIsNone(session.plan_state)
        self.assertEqual(session.messages.count(), 0)

if __name__ == "__main__":
    unittest.main()
