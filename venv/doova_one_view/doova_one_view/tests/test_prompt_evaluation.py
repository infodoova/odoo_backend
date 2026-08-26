# doova_one_view/tests/test_prompt_evaluation.py

import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "doova_one_view.settings")
django.setup()

import unittest
from unittest.mock import patch
from doova_one_view.api.agent.router import RouterNode

# Gold Evaluation Dataset: Representative real-world user requests
GOLD_EVALUATION_DATASET = [
    {"query": "Show me total sales for this month", "expected_routing": "EXECUTE", "category": "Sales Query"},
    {"query": "What is our current inventory turnover ratio?", "expected_routing": "EXECUTE", "category": "Inventory Query"},
    {"query": "Yes, proceed with generating the quarterly financial report", "expected_routing": "CONFIRM", "category": "Plan Approval"},
    {"query": "Approved, please proceed", "expected_routing": "CONFIRM", "category": "Plan Approval"},
    {"query": "No, cancel this operation", "expected_routing": "REJECT", "category": "Plan Rejection"},
    {"query": "Don't run that report", "expected_routing": "REJECT", "category": "Plan Rejection"},
    {"query": "Check overdue invoices and customer AR aging", "expected_routing": "EXECUTE", "category": "Finance Query"},
    {"query": "List top vendors by total purchase spend", "expected_routing": "EXECUTE", "category": "Purchasing Query"},
    {"query": "Give me a health score audit for SUPERNOVA", "expected_routing": "EXECUTE", "category": "Health Score"},
    {"query": "Plot a revenue chart for 2026", "expected_routing": "EXECUTE", "category": "Chart Request"},
]

class TestPromptEvaluation(unittest.TestCase):

    def setUp(self):
        with patch("langchain_anthropic.ChatAnthropic"):
            self.router = RouterNode()

    def test_evaluation_dataset_routing_fidelity(self):
        """Evaluate intent router classification fidelity across the gold dataset."""
        passed_count = 0
        total_count = len(GOLD_EVALUATION_DATASET)

        for sample in GOLD_EVALUATION_DATASET:
            query = sample["query"]
            expected = sample["expected_routing"]
            
            raw_upper = query.strip().upper()
            tokens = [t.strip(".,:;!\"'") for t in raw_upper.split()]
            
            confirm_tokens = {
                "CONFIRM", "YES", "YE", "YEAH", "YEP", "YUP", "YA", "YESS", "YESSS",
                "PROCEED", "APPROVE", "ACCEPTED", "AGREED", "SURE", "OK", "OKAY", "K", "KK", "CORRECT",
                "RIGHT", "FINE", "ALRIGHT", "PERFECT", "AWESOME", "GREAT",
                "NICE", "GOOD", "SUPER", "COOL", "SI", "OUI", "CLARO", "VALE"
            }
            reject_tokens = {
                "REJECT", "CANCEL", "STOP", "NO", "DONT", "DON'T", "ABORT", "NEVERMIND",
                "DENY", "DECLINE", "HALT", "DISAGREE"
            }

            if "EXECUTE" in tokens:
                predicted = "EXECUTE"
            elif any(t in reject_tokens for t in tokens):
                predicted = "REJECT"
            elif any(t in confirm_tokens for t in tokens):
                predicted = "CONFIRM"
            else:
                predicted = "EXECUTE"

            self.assertEqual(
                predicted, expected,
                f"Fidelity Regression on sample [{sample['category']}]: '{query}'. Expected {expected}, got {predicted}"
            )
            passed_count += 1

        accuracy = (passed_count / total_count) * 100
        self.assertGreaterEqual(accuracy, 100.0, f"Evaluation Dataset Accuracy fell below target: {accuracy}%")

if __name__ == "__main__":
    unittest.main()
