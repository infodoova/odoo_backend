# doova_one_view/tests/test_emoji_badges_and_tables.py

import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "doova_one_view.settings")
django.setup()

import unittest
from doova_one_view.api.agent.tools_refactored.emoji_to_badges import normalize_status_emoji

class TestEmojiBadgesAndTables(unittest.TestCase):

    def test_normalize_status_emoji_bracket_replacement(self):
        """Verify bracketed tags like [Alert] and [Warning] are converted to HTML badge spans."""
        input_text = "[Alert] System Offline. [Warning] Battery Low."
        normalized = normalize_status_emoji(input_text)
        self.assertIn('<span class="badge badge-critical">SYSTEM OFFLINE</span>', normalized)
        self.assertIn('<span class="badge badge-warning">BATTERY LOW</span>', normalized)

    def test_normalize_status_emoji_custom_trailing_word(self):
        """Verify bracket tags with trailing custom words preserve the custom label."""
        input_text = "[Critical] Stock Out"
        normalized = normalize_status_emoji(input_text)
        self.assertIn('<span class="badge badge-critical">STOCK OUT</span>', normalized)

    def test_normalize_status_emoji_empty_and_plain_text(self):
        """Verify empty input or plain text without status badges remains unchanged."""
        self.assertEqual(normalize_status_emoji(""), "")
        self.assertIsNone(normalize_status_emoji(None))
        plain = "Total sales for 2026 were $1,250,000."
        self.assertEqual(normalize_status_emoji(plain), plain)

if __name__ == "__main__":
    unittest.main()
