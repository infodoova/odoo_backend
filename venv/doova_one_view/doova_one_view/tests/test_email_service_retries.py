# doova_one_view/tests/test_email_service_retries.py

import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "doova_one_view.settings")
django.setup()

import unittest
from unittest.mock import patch, MagicMock
from asgiref.sync import async_to_sync
from doova_one_view.api.email.service import EmailService, EmailServiceError


class TestEmailServiceRetries(unittest.TestCase):

    @patch("django.core.mail.EmailMultiAlternatives.send")
    def test_email_send_succeeds_first_attempt(self, mock_send):
        mock_send.return_value = 1
        res = async_to_sync(EmailService.send)(
            to="user@example.com",
            subject="Test Subject",
            html_body="<p>Test</p>",
            max_retries=3,
        )
        self.assertEqual(res["status"], "sent")
        self.assertEqual(res["attempts"], 1)
        self.assertEqual(mock_send.call_count, 1)

    @patch("asyncio.sleep")
    @patch("django.core.mail.EmailMultiAlternatives.send")
    def test_email_send_succeeds_after_retry(self, mock_send, mock_sleep):
        # Fail first 2 attempts with SMTPException, succeed on 3rd attempt
        mock_send.side_effect = [Exception("SMTP Connection Refused"), Exception("Timeout"), 1]
        res = async_to_sync(EmailService.send)(
            to="user@example.com",
            subject="Test Retry",
            html_body="<p>Test</p>",
            max_retries=3,
            backoff_seconds=0.01,
        )
        self.assertEqual(res["status"], "sent")
        self.assertEqual(res["attempts"], 3)
        self.assertEqual(mock_send.call_count, 3)

    @patch("asyncio.sleep")
    @patch("django.core.mail.EmailMultiAlternatives.send")
    def test_email_send_fails_after_max_retries(self, mock_send, mock_sleep):
        mock_send.side_effect = Exception("Permanent SMTP Connection Failure")
        with self.assertRaises(EmailServiceError) as ctx:
            async_to_sync(EmailService.send)(
                to="user@example.com",
                subject="Test Permanent Failure",
                html_body="<p>Test</p>",
                max_retries=3,
                backoff_seconds=0.01,
            )
        self.assertIn("Could not send email after 3 attempts", str(ctx.exception))
        self.assertEqual(mock_send.call_count, 3)


if __name__ == "__main__":
    unittest.main()
