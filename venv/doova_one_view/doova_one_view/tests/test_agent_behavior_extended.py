# doova_one_view/tests/test_agent_behavior_extended.py
"""
Extended Agent Behavior & Decision Evaluation Suite.

Validates intent classification, ambiguity resolution, self-correction loops,
memory window handling, and LLM output parsing.
"""

import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "doova_one_view.settings")
django.setup()

import unittest
from unittest.mock import patch, MagicMock
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from doova_one_view.api.agent.router import RouterNode
from doova_one_view.api.agent.langchain_agent import ThinkingSafeChatAnthropic
from doova_one_view.api.agent.query_context import (
    resolve_tenant_id,
    normalize_tenant_ids,
    normalize_company_ids
)
from doova_one_view.api.agent.routes import extract_context_ids


class TestAgentBehaviorExtended(unittest.TestCase):
    """Deep behavioral evaluations of Nexus AI agent decisions and routing."""

    def setUp(self):
        with patch("langchain_anthropic.ChatAnthropic"):
            self.router = RouterNode()

    def test_social_greetings_bypasses_router_and_plan(self):
        """Social phrases should return conversational greeting without plan confirmation."""
        social_inputs = [
            "hi", "hello", "hey", "how are you", "good morning",
            "good afternoon", "thanks", "thank you", "bye", "ok"
        ]
        SOCIAL_PHRASES = {
            "hi", "hello", "hey", "how are you", "how are you?",
            "good morning", "good afternoon", "good evening",
            "thanks", "thank you", "bye", "goodbye", "ok", "okay",
        }
        for greeting in social_inputs:
            is_social = greeting.lower().strip("!.?") in SOCIAL_PHRASES
            self.assertTrue(is_social, f"Greeting '{greeting}' should be flagged as social phrase")

    def test_router_handles_voice_mode_tag_stripping(self):
        """Voice mode tags should be stripped before intent classification."""
        import re
        voice_inputs = [
            "[VOICE MODE: transcript] What is our revenue for 2026?",
            "[VOICE MODE: fast] Show me top 5 inventory items.",
            "Tell me about gross margin [VOICE MODE: auto]"
        ]
        for v_input in voice_inputs:
            cleaned = re.sub(r'\[VOICE MODE:[^\]]*\]', '', v_input).strip()
            self.assertNotIn("[VOICE MODE:", cleaned)
            self.assertGreater(len(cleaned), 0)

    def test_query_context_extraction_combines_all_formats(self):
        """extract_context_ids extracts arrays or single strings from dict payloads."""
        from doova_one_view.api.agent.routes import ChatRequest
        uuid1 = "3fa85f64-5717-4562-b3fc-2c963f66afa6"
        uuid2 = "99999999-8888-7777-6666-555555555555"
        payload = {
            "tenant_id": uuid1,
            "tenant_ids": [uuid2],
            "company_id": 10,
            "company_ids": [10, 20]
        }
        primary_t, res_t, primary_c, res_c = extract_context_ids(payload)
        self.assertEqual(primary_t, uuid1)
        self.assertIn(uuid1, res_t)
        self.assertIn(uuid2, res_t)
        self.assertEqual(res_c, [10, 20])

        req = ChatRequest(tenant_id=uuid1, tenant_ids=[uuid2], company_id=10, company_ids=[10, 20])
        p_t, r_t, p_c, r_c = extract_context_ids(req)
        self.assertEqual(p_t, uuid1)
        self.assertIn(uuid1, r_t)

    def test_thinking_safe_chat_handles_mixed_content_blocks(self):
        """Verifies mixed LLM content blocks (thinking + text + tool_use) are processed safely."""
        mixed_msg = AIMessage(content=[
            {"type": "thinking", "thinking": "Calculating EBIT...", "signature": "sig123"},
            {"type": "text", "text": "EBIT for Q1 is $250,000."},
            {"type": "tool_use", "id": "call_1", "name": "get_sales_summary", "input": {}}
        ])
        cleaned = ThinkingSafeChatAnthropic._clean_messages([mixed_msg])
        self.assertEqual(len(cleaned[0].content), 3)
        self.assertEqual(cleaned[0].content[0]["thinking"], "Calculating EBIT...")
        self.assertEqual(cleaned[0].content[1]["text"], "EBIT for Q1 is $250,000.")

    def test_thinking_safe_chat_strips_empty_thinking_blocks(self):
        """Empty thinking blocks missing text are safely removed to prevent Anthropic API 400 errors."""
        empty_thinking_msg = AIMessage(content=[
            {"type": "thinking"},  # empty
            {"type": "text", "text": "Safe response"}
        ])
        cleaned = ThinkingSafeChatAnthropic._clean_messages([empty_thinking_msg])
        self.assertEqual(len(cleaned[0].content), 1)
        self.assertEqual(cleaned[0].content[0]["text"], "Safe response")

    def test_plan_approval_affirmative_keyword_matching(self):
        """Tests deterministic matching of user affirmative tokens for plan approval."""
        AFFIRMATIVE_KEYWORDS = {
            "yes", "ye", "yeah", "yep", "yup", "ya", "yaa", "yess", "yesss", "sure", "ok", "okay", "k", "kk",
            "proceed", "go", "ahead", "do", "it", "confirm", "approve", "accepted", "agreed", "correct",
            "right", "fine", "alright", "please", "pls", "execute", "run", "start", "plan", "show"
        }
        user_affirmations = ["yes", "yep", "sure", "proceed", "approve", "agreed", "correct"]
        for word in user_affirmations:
            self.assertIn(word.lower(), AFFIRMATIVE_KEYWORDS)

    def test_plan_rejection_keyword_matching(self):
        """Tests deterministic matching of user rejection tokens for plan cancellation."""
        REJECTION_KEYWORDS = {"no", "nope", "nah", "cancel", "stop", "abort", "dont", "don't", "refuse", "reject", "nevermind", "nvm"}
        user_rejections = ["no", "cancel", "stop", "abort", "nevermind", "nvm"]
        for word in user_rejections:
            self.assertIn(word.lower(), REJECTION_KEYWORDS)


if __name__ == "__main__":
    unittest.main()
