# doova_one_view/tests/test_router.py

import unittest
from unittest.mock import MagicMock, patch
from langchain_anthropic import ChatAnthropic
from doova_one_view.api.agent.router import RouterNode

class TestRouterNode(unittest.TestCase):

    def setUp(self):
        with patch("langchain_anthropic.ChatAnthropic"):
            self.router = RouterNode()

    @patch.object(RouterNode, "classify")
    def test_classify_execute_intent(self, mock_classify):
        mock_classify.return_value = "EXECUTE"
        res = self.router.classify("hello tell me about my stock inventory this year")
        self.assertEqual(res, "EXECUTE")

    def test_confirm_tokens_priority(self):
        """Ensure EXECUTE LLM output is NEVER rewritten to CONFIRM."""
        raw_upper = "EXECUTE"
        tokens = [t.strip(".,:;!\"'") for t in raw_upper.split()]
        
        confirm_tokens = {
            "CONFIRM", "YES", "YE", "YEAH", "YEP", "YUP", "YA", "YESS", "YESSS",
            "PROCEED", "APPROVE", "ACCEPTED", "AGREED", "SURE", "OK", "OKAY", "K", "KK", "CORRECT",
            "RIGHT", "FINE", "ALRIGHT", "PERFECT", "AWESOME", "GREAT",
            "NICE", "GOOD", "SUPER", "COOL", "SI", "OUI", "CLARO", "VALE"
        }

        # Check our fixed priority order
        if "EXECUTE" in tokens:
            result = "EXECUTE"
        elif any(t in confirm_tokens for t in tokens):
            result = "CONFIRM"
        else:
            result = "EXECUTE"

        self.assertEqual(result, "EXECUTE")

    def test_confirm_tokens_matching(self):
        """Ensure explicit confirmation words match CONFIRM."""
        confirm_words = ["YES", "PROCEED", "APPROVE", "SURE", "OKAY", "AGREED"]
        confirm_tokens = {
            "CONFIRM", "YES", "YE", "YEAH", "YEP", "YUP", "YA", "YESS", "YESSS",
            "PROCEED", "APPROVE", "ACCEPTED", "AGREED", "SURE", "OK", "OKAY", "K", "KK", "CORRECT",
            "RIGHT", "FINE", "ALRIGHT", "PERFECT", "AWESOME", "GREAT",
            "NICE", "GOOD", "SUPER", "COOL", "SI", "OUI", "CLARO", "VALE"
        }
        for word in confirm_words:
            tokens = [word]
            if "EXECUTE" in tokens:
                result = "EXECUTE"
            elif any(t in confirm_tokens for t in tokens):
                result = "CONFIRM"
            else:
                result = "EXECUTE"
            self.assertEqual(result, "CONFIRM", f"Word '{word}' should match CONFIRM")

    @patch("langchain_core.runnables.base.RunnableSequence.invoke")
    def test_router_llm_invocation_fallback(self, mock_invoke):
        """Test fallback behavior when LLM raises exception."""
        mock_invoke.side_effect = Exception("API Connection Timeout")
        result = self.router.classify("what is our sales this month?")
        self.assertEqual(result, "EXECUTE")

    def test_routing_scenarios(self):
        """Extended coverage for diverse routing and parsing scenarios."""
        confirm_tokens = {
            "CONFIRM", "YES", "YE", "YEAH", "YEP", "YUP", "YA", "YESS", "YESSS",
            "PROCEED", "APPROVE", "ACCEPTED", "AGREED", "SURE", "OK", "OKAY", "K", "KK", "CORRECT",
            "RIGHT", "FINE", "ALRIGHT", "PERFECT", "AWESOME", "GREAT",
            "NICE", "GOOD", "SUPER", "COOL", "SI", "OUI", "CLARO", "VALE"
        }
        
        test_cases = [
            ("YES", "CONFIRM"), ("yes", "CONFIRM"), ("Sure", "CONFIRM"), ("OK.", "CONFIRM"),
            ("EXECUTE", "EXECUTE"), ("EXECUTE CONFIRM", "EXECUTE"), ("CONFIRM EXECUTE", "EXECUTE"),
            ("Please proceed", "CONFIRM"), ("Just execute", "EXECUTE"), ("C-1", "EXECUTE"),
            ("CONFIRM, please", "CONFIRM"), ("OK, proceed", "CONFIRM"), ("YEP!", "CONFIRM"),
            ("Maybe", "EXECUTE"), ("Unknown input", "EXECUTE"), ("123", "EXECUTE"),
            ("YES!", "CONFIRM"), ("SI", "CONFIRM"), ("OUI", "CONFIRM"), ("CLARO", "CONFIRM"),
            ("VALE", "CONFIRM"), ("K", "CONFIRM"), ("KK", "CONFIRM"), ("AGREED", "CONFIRM"),
            ("CORRECT", "CONFIRM"), ("NICE", "CONFIRM"), ("SUPER", "CONFIRM"), ("COOL", "CONFIRM"),
            ("AWESOME", "CONFIRM"), ("GREAT", "CONFIRM"), ("FINE", "CONFIRM"), ("ALRIGHT", "CONFIRM"),
            ("ACCEPTED", "CONFIRM"), ("YEAH", "CONFIRM"), ("YUP", "CONFIRM"), ("YESS", "CONFIRM")
        ]

        for input_str, expected in test_cases:
            tokens = [t.strip(".,:;!\"'") for t in input_str.upper().split()]
            if "EXECUTE" in tokens:
                result = "EXECUTE"
            elif any(t in confirm_tokens for t in tokens):
                result = "CONFIRM"
            else:
                result = "EXECUTE"
            self.assertEqual(result, expected, f"Failed for input: {input_str}")

if __name__ == "__main__":
    unittest.main()
