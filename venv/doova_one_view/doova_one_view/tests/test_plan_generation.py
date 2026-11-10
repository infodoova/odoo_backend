"""
Phase 2 of AGENT_FIXES_PLAN.md: plan generation, plan formatting and plan approval.

No database and no network: the model is replaced with a stub.
"""

import json
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from doova_one_view.api.agent.reasoning import (
    PLAN_GENERATION_TRIES,
    PlanGenerationError,
    ReasoningNode,
)
from doova_one_view.api.agent.routes import format_plan_for_chat, is_plan_approval

VALID_PLAN = {
    "plan_id": "working_capital_90_day",
    "strategic_objective": "Free up cash tied in stock and receivables",
    "steps": [
        {"step": 1, "description": "Read the business profile", "tools": ["tenant_profile"]},
        {"step": 2, "description": "Check overdue invoices", "tools": ["aging_analysis"]},
    ],
    "expected_outcome": "A ranked list of cash releases",
}


def _reply(content, stop_reason=None):
    return MagicMock(content=content, response_metadata={"stop_reason": stop_reason} if stop_reason else {})


def _node(*replies):
    """A ReasoningNode whose model returns the given replies in order."""
    with patch("doova_one_view.api.agent.reasoning.DoovaLangChainAgent"):
        node = ReasoningNode()
    node.agent.model_name = "claude-opus-5-5"
    node.agent.llm.invoke.side_effect = list(replies)
    return node


class CreatePlanTests(SimpleTestCase):
    def test_plain_json_reply_returns_the_plan(self):
        node = _node(_reply(json.dumps(VALID_PLAN)))
        self.assertEqual(node.create_plan("90 day roadmap"), VALID_PLAN)
        self.assertEqual(node.agent.llm.invoke.call_count, 1)

    def test_fenced_json_reply_returns_the_plan(self):
        node = _node(_reply("```json\n" + json.dumps(VALID_PLAN) + "\n```"))
        self.assertEqual(node.create_plan("roadmap"), VALID_PLAN)

    def test_list_of_blocks_with_thinking_returns_the_plan(self):
        blocks = [
            {"type": "thinking", "thinking": "Let me plan...", "signature": "sig"},
            {"type": "text", "text": json.dumps(VALID_PLAN)},
        ]
        node = _node(_reply(blocks))
        self.assertEqual(node.create_plan("roadmap"), VALID_PLAN)

    def test_retries_once_with_a_stricter_instruction(self):
        node = _node(_reply("Sure! Here is my plan in prose."), _reply(json.dumps(VALID_PLAN)))
        self.assertEqual(node.create_plan("roadmap"), VALID_PLAN)
        self.assertEqual(node.agent.llm.invoke.call_count, 2)
        first_prompt = node.agent.llm.invoke.call_args_list[0].args[0]
        second_prompt = node.agent.llm.invoke.call_args_list[1].args[0]
        self.assertIn("could not be read as the required JSON plan", second_prompt)
        self.assertNotIn("could not be read as the required JSON plan", first_prompt)

    def test_garbage_twice_raises_instead_of_returning_an_empty_plan(self):
        node = _node(_reply("no json here"), _reply("still no json"))
        with self.assertRaises(PlanGenerationError):
            node.create_plan("roadmap")
        self.assertEqual(node.agent.llm.invoke.call_count, PLAN_GENERATION_TRIES)

    def test_json_without_steps_is_not_a_usable_plan(self):
        # This is the shape of the old silent fallback stub.
        stub = {"plan_id": "auto", "status": "PENDING_APPROVAL", "question_summary": "roadmap"}
        node = _node(_reply(json.dumps(stub)), _reply(json.dumps(stub)))
        with self.assertRaises(PlanGenerationError):
            node.create_plan("roadmap")

    def test_empty_steps_list_is_not_a_usable_plan(self):
        empty = dict(VALID_PLAN, steps=[])
        node = _node(_reply(json.dumps(empty)), _reply(json.dumps(empty)))
        with self.assertRaises(PlanGenerationError):
            node.create_plan("roadmap")

    def test_reply_cut_off_at_token_limit_is_rejected_even_if_it_can_be_repaired(self):
        # The extractor would close the brackets and return a plan with only step 1.
        cut = '{"plan_id": "p", "steps": [{"step": 1, "description": "a", "tools": ["x"]}, {"step": 2, "desc'
        node = _node(_reply(cut, "max_tokens"), _reply(cut, "max_tokens"))
        with self.assertRaises(PlanGenerationError):
            node.create_plan("roadmap")
        self.assertEqual(node.agent.llm.invoke.call_count, PLAN_GENERATION_TRIES)

    def test_cut_off_first_reply_then_complete_second_reply_succeeds(self):
        cut = '{"plan_id": "p", "steps": [{"step": 1, "description": "a"'
        node = _node(_reply(cut, "max_tokens"), _reply(json.dumps(VALID_PLAN), "end_turn"))
        self.assertEqual(node.create_plan("roadmap"), VALID_PLAN)

    def test_token_usage_is_recorded_even_when_planning_fails(self):
        node = _node(_reply("nope"), _reply("nope"))
        usage = {}
        with self.assertRaises(PlanGenerationError):
            node.create_plan("roadmap", usage_out=usage)
        self.assertIn("total_tokens", usage)
        self.assertEqual(usage["llm_calls"], 0)  # the stub model reports no usage events
        self.assertEqual(node.agent.last_token_usage, usage)

    def test_each_call_gets_its_own_counter(self):
        node = _node(_reply(json.dumps(VALID_PLAN)), _reply(json.dumps(VALID_PLAN)))
        first, second = {}, {}
        node.create_plan("a", usage_out=first)
        node.create_plan("b", usage_out=second)
        self.assertIsNot(first, second)
        handlers = [c.kwargs["config"]["callbacks"][0] for c in node.agent.llm.invoke.call_args_list]
        self.assertIsNot(handlers[0], handlers[1])


class FormatPlanTests(SimpleTestCase):
    def test_steps_and_tools_are_listed(self):
        text = format_plan_for_chat(VALID_PLAN)
        self.assertIn("### Strategic Architecture Plan", text)
        self.assertIn("**Objective:** Free up cash tied in stock and receivables", text)
        self.assertIn("1. **Step 1**: Read the business profile *(Tools: tenant_profile)*", text)
        self.assertIn("2. **Step 2**: Check overdue invoices *(Tools: aging_analysis)*", text)
        self.assertIn("**Expected Outcome:** A ranked list of cash releases", text)
        self.assertTrue(text.endswith("*This is a high-stakes request. Shall I proceed with this plan?*"))

    def test_background_version_has_its_own_title_and_footer(self):
        text = format_plan_for_chat(VALID_PLAN, background=True)
        self.assertIn("(Completed in Background)", text)
        self.assertTrue(text.endswith("*Plan execution is ready. Shall I proceed with this plan?*"))

    def test_legacy_objective_and_phases_are_still_rendered(self):
        text = format_plan_for_chat({"objective": "Grow sales", "phases": ["Audit", {"title": "Act", "description": "Do it"}]})
        self.assertIn("**Objective:** Grow sales", text)
        self.assertIn("1. **Audit**", text)
        self.assertIn("2. **Act**: Do it", text)

    def test_the_real_objective_is_shown_not_the_default(self):
        self.assertNotIn("Strategic Analysis", format_plan_for_chat(VALID_PLAN))


class PlanApprovalTests(SimpleTestCase):
    def test_short_affirmations_approve(self):
        for msg in ("yes", "Yes, proceed with the plan", "go ahead", "ok", "نعم", "oui", "d'accord"):
            with self.subTest(msg=msg):
                self.assertTrue(is_plan_approval(msg))

    def test_a_question_containing_an_affirmative_word_is_not_an_approval(self):
        for msg in ("what is a good margin?", "what is a good margin", "Is a 20% margin good?", "هل هذا جيد؟"):
            with self.subTest(msg=msg):
                self.assertFalse(is_plan_approval(msg))

    def test_a_long_message_is_not_an_approval(self):
        msg = "yes " + "and then also show me the full breakdown of every product by region for last year"
        self.assertFalse(is_plan_approval(msg))

    def test_rejection_wins(self):
        for msg in ("no", "cancel", "yes but cancel that"):
            with self.subTest(msg=msg):
                self.assertFalse(is_plan_approval(msg))

    def test_empty_and_none_do_not_approve(self):
        self.assertFalse(is_plan_approval(""))
        self.assertFalse(is_plan_approval(None))
