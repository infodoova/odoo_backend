# doova_one_view/tests/test_agent_utils.py

import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "doova_one_view.settings")
django.setup()

import unittest
from doova_one_view.api.agent.utils import (
    parse_json_chart_from_text,
    strip_json_chart_from_text,
    parse_graph_data_from_text,
    fix_currency_symbols,
)

class TestAgentUtils(unittest.TestCase):

    def test_parse_json_chart_fenced(self):
        text = """
        Here is the sales performance chart:
        ```json
        {
          "type": "chart",
          "title": "Monthly Revenue",
          "chart": {
            "type": "bar",
            "data": [{"name": "Jan", "value": 100}, {"name": "Feb", "value": 200}]
          }
        }
        ```
        """
        parsed = parse_json_chart_from_text(text)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["type"], "chart")
        self.assertEqual(parsed["title"], "Monthly Revenue")

    def test_strip_json_chart_from_text(self):
        text = "Hello!\n```json\n{\"type\": \"chart\", \"chart\": {}}\n```\nHere is your financial advice."
        cleaned = strip_json_chart_from_text(text)
        self.assertNotIn("```json", cleaned)
        self.assertIn("Here is your financial advice", cleaned)

    def test_parse_graph_data_from_markdown_table(self):
        table_text = """
        | Category | Amount |
        | --- | --- |
        | AC Unit | 50000 |
        | TV Unit | 75000 |
        """
        data = parse_graph_data_from_text(table_text)
        self.assertIsNotNone(data)
        self.assertEqual(len(data), 2)
        self.assertEqual(data[0]["name"], "AC Unit")
        self.assertEqual(data[0]["value"], 50000.0)

    def test_fix_currency_symbols(self):
        text_usd = "Total revenue was $10000."
        res_xaf = fix_currency_symbols(text_usd, "XAF")
        self.assertEqual(res_xaf, "Total revenue was XAF 10000.")

if __name__ == "__main__":
    unittest.main()
