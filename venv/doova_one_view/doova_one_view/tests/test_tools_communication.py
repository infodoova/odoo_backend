# doova_one_view/tests/test_tools_communication.py

import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "doova_one_view.settings")
django.setup()

import unittest
from unittest.mock import patch
from doova_one_view.api.agent.tools_refactored.communication import (
    send_alert_tool,
    send_email_tool,
    _format_alert_email_html,
)


class TestCommunicationTools(unittest.TestCase):

    def test_format_alert_email_html(self):
        html = _format_alert_email_html(
            title="Overdue Accounts Receivable",
            message="Overdue AR exceeds 30% of total receivables.",
            severity="critical",
            tenant_id="test-tenant",
        )
        self.assertIn("CRITICAL ALERT", html)
        self.assertIn("Overdue Accounts Receivable", html)
        self.assertIn("test-tenant", html)

    def test_format_alert_email_html_critical_auto_classification(self):
        html = _format_alert_email_html(
            title="100% of Receivables Overdue",
            message="All XAF 480.8M in outstanding receivables is past due, with cash reserves of only XAF 44.2M.",
            severity="info",
            tenant_id="78191733-c06a-4238-a44c-27fbbf66edf4",
        )
        self.assertIn("CRITICAL ALERT", html)
        self.assertNotIn("INFORMATION UPDATE", html)

    def test_format_alert_email_html_markdown_rendering(self):
        full_md_report = (
            "100% of receivables (XAF 480.8M) are overdue, with cash reserves of only XAF 44.2M.\n\n"
            "## What Happened\n"
            "- **Accounts Receivable Overdue Ratio: 100%** — Every single XAF 480,833,696 is past due.\n"
            "- **Customer concentration**: Two customers owe **XAF 301,074,340**.\n\n"
            "## Business Impact\n"
            "- With 100% AR overdue and cash reserves of XAF 44.2M, liquidity is constrained.\n\n"
            "## Recommended Action\n"
            "1. Escalate collections on Seguibat S.A and Construction Company.\n"
            "2. Freeze credit terms."
        )
        html = _format_alert_email_html(
            title="Critical: 100% of Receivables Overdue",
            message=full_md_report,
            severity="info",
            tenant_id="78191733-c06a-4238-a44c-27fbbf66edf4",
        )
        self.assertIn("CRITICAL ALERT", html)
        self.assertIn('<h3 style="font-size:15px;font-weight:700;color:#1e3a5f;margin:16px 0 5px;padding-bottom:4px;border-bottom:1.5px solid #dbeafe;">What Happened</h3>', html)
        self.assertIn('<strong>Accounts Receivable Overdue Ratio: 100%</strong>', html)
        self.assertIn('<li style="font-size:13px;color:#374151;line-height:1.6;margin-bottom:3px;">', html)
        self.assertIn('<ol style="margin:6px 0 10px 18px;padding:0;">', html)

    def test_send_email_tool_invalid_email(self):

        res = send_email_tool(
            tenant_id="test-tenant",
            to_email="invalid-email-string",
            subject="Test Subject",
            body="Test Body",
        )
        self.assertFalse(res["sent"])
        self.assertEqual(res["status"], "invalid_email")

    @patch("doova_one_view.api.email.service.EmailService.send")
    def test_send_email_tool_success(self, mock_send):
        mock_send.return_value = {"status": "sent"}
        res = send_email_tool(
            tenant_id="test-tenant",
            to_email="finance@example.com",
            subject="Monthly Report Summary",
            body="Here is your monthly summary.",
        )
        self.assertTrue(res["sent"])
        self.assertEqual(res["email"]["status"], "sent")
        mock_send.assert_called_once()

    @patch("doova_one_view.api.email.service.EmailService.send")
    def test_send_alert_tool_direct_email(self, mock_send):
        mock_send.return_value = {"status": "sent"}
        res = send_alert_tool(
            tenant_id="test-tenant",
            title="Cash Reserve Warning",
            message="Cash reserves dropped 25%.",
            severity="warning",
            to_email="cfo@example.com",
        )
        self.assertTrue(res["sent"])
        self.assertEqual(res["alert"]["severity"], "warning")
        self.assertEqual(res["recipients_notified"], 1)
        mock_send.assert_called_once()

    def test_serialize_alert_context(self):
        from doova_one_view.api.agent.tools_refactored.communication import serialize_alert_context, MAX_ALERT_PAYLOAD_BYTES
        import json

        json_str = serialize_alert_context(
            tenant_id="tenant-123",
            user_prompt="Alert me if sales reach 500M",
            thresholds={"revenue_drop_pct": 20},
            company_ids=[1, 2],
            precheck_summary="AR Overdue 35%"
        )
        data = json.loads(json_str)
        self.assertEqual(data["tenant_id"], "tenant-123")
        self.assertEqual(data["prompt"], "Alert me if sales reach 500M")
        self.assertEqual(data["thresholds"]["revenue_drop_pct"], 20)
        self.assertLessEqual(len(json_str.encode("utf-8")), MAX_ALERT_PAYLOAD_BYTES)

    def test_serialize_alert_context_large_payload_truncation(self):
        from doova_one_view.api.agent.tools_refactored.communication import serialize_alert_context, MAX_ALERT_PAYLOAD_BYTES
        import json

        huge_prompt = "X" * 10000
        json_str = serialize_alert_context(
            tenant_id="tenant-123",
            user_prompt=huge_prompt,
        )
        self.assertLessEqual(len(json_str.encode("utf-8")), MAX_ALERT_PAYLOAD_BYTES)
        data = json.loads(json_str)
        self.assertTrue(data["prompt"].endswith("... [truncated]"))

    def test_parse_llm_response_json_layer(self):
        from doova_one_view.api.jobs.alert_job import AlertJobManager

        json_response = '''
```json
{
  "condition_triggered": true,
  "severity": "critical",
  "summary": "Sales exceeded 500M milestone."
}
```
'''
        summary, cond, sev = AlertJobManager._parse_llm_response(json_response)
        self.assertTrue(cond)
        self.assertEqual(sev, "critical")
        self.assertEqual(summary, "Sales exceeded 500M milestone.")

    def test_parse_llm_response_text_severity_prefix_layer(self):
        from doova_one_view.api.jobs.alert_job import AlertJobManager

        text_response = "CRITICAL: Receivables 100% overdue\n\n## What Happened\nDetailed report here."
        summary, cond, sev = AlertJobManager._parse_llm_response(text_response)
        self.assertTrue(cond)
        self.assertEqual(sev, "critical")
        self.assertIn("Receivables 100% overdue", summary)

    def test_parse_llm_response_fallback_layers(self):
        from doova_one_view.api.jobs.alert_job import AlertJobManager

        # Layer 3 - Strategic recommendation keyword scan
        rec_response = "## STRATEGIC RECOMMENDATION\nWARNING: Cash flow low."
        summary, cond, sev = AlertJobManager._parse_llm_response(rec_response)
        self.assertTrue(cond)
        self.assertEqual(sev, "warning")

        # Layer 4 - Ultimate safe fallback for garbage / empty
        summary, cond, sev = AlertJobManager._parse_llm_response("")
        self.assertFalse(cond)
        self.assertEqual(sev, "info")

        summary, cond, sev = AlertJobManager._parse_llm_response("Random text with no severity keywords")
        self.assertFalse(cond)
        self.assertEqual(sev, "info")

    @patch("doova_one_view.api.jobs.alert_prechecks.run_all_prechecks")
    @patch("doova_one_view.api.agent.langchain_agent.DoovaLangChainAgent.run")
    def test_detect_anomalies_quota_error_handling(self, mock_agent_run, mock_prechecks):
        from doova_one_view.api.jobs.alert_job import AlertJobManager
        from asgiref.sync import async_to_sync

        mock_prechecks.return_value = {"any_triggered": True, "triggered_checks": ["ar_overdue"], "precheck_summary": "AR > 30%"}
        mock_agent_run.side_effect = Exception("anthropic.BadRequestError: Your credit balance is too low to access the Anthropic API")

        summary, cond, sev = async_to_sync(AlertJobManager._detect_anomalies)(
            tenant_id="test-tenant",
            company_ids=[1],
            user_prompt="Check sales"
        )
        self.assertFalse(cond)
        self.assertEqual(sev, "info")
        self.assertIn("AI Advisor Service Temporarily Unavailable", summary)
        self.assertIn("upstream LLM provider credit limits", summary)

    def test_http_exception_handler_top_level_error_format(self):
        from starlette.exceptions import HTTPException as StarletteHTTPException
        from doova_one_view.api.common.handlers import http_exception_handler
        from asgiref.sync import async_to_sync
        import json

        exc = StarletteHTTPException(
            status_code=429,
            detail="Rate limit: Please wait 18 seconds before triggering run-now again for this schedule."
        )
        response = async_to_sync(http_exception_handler)(None, exc)
        data = json.loads(response.body.decode("utf-8"))

        self.assertEqual(response.status_code, 429)
        self.assertEqual(data["message"], "Rate limit: Please wait 18 seconds before triggering run-now again for this schedule.")
        self.assertEqual(data["message_type"], "error")
        self.assertNotIn("detail", data)


if __name__ == "__main__":
    unittest.main()



