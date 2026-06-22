"""
Shared email service — wraps the SMTP gateway API.

Usage:
    await EmailService.send_otp_email(to_email, to_name, otp_code)
    await EmailService.send_report_email(to_email, to_name, subject, html_body, attachments)
"""

import logging
import httpx
from typing import Optional
from django.conf import settings

logger = logging.getLogger(__name__)


class EmailServiceError(Exception):
    pass


class EmailService:

    @staticmethod
    def _headers() -> dict:
        token = settings.SMTP_GATEWAY_TOKEN
        if not token:
            raise EmailServiceError("SMTP_GATEWAY_TOKEN is not configured")
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _base_url() -> str:
        url = settings.SMTP_GATEWAY_URL
        if not url:
            raise EmailServiceError("SMTP_GATEWAY_URL is not configured")
        return url.rstrip("/")

    @staticmethod
    async def send(
        to: str,
        subject: str,
        html_body: str,
        to_name: Optional[str] = None,
        text_body: Optional[str] = None,
        priority: str = "NORMAL",
        attachments: Optional[list] = None,
    ) -> dict:
        """
        Low-level send. Returns the gateway response dict { jobId, status }.
        Raises EmailServiceError on any failure.
        """
        payload: dict = {
            "to": to,
            "subject": subject,
            "htmlBody": html_body,
            "priority": priority,
        }
        if to_name:
            payload["toName"] = to_name
        if text_body:
            payload["textBody"] = text_body
        if attachments:
            payload["attachments"] = attachments

        url = f"{EmailService._base_url()}/emails/send"

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(url, json=payload, headers=EmailService._headers())

            if response.status_code in (200, 201):
                body = response.json()
                # Gateway wraps response: { success, data: { jobId, status } }
                return body.get("data", body)

            logger.error(
                "SMTP gateway error %s: %s",
                response.status_code,
                response.text,
            )
            raise EmailServiceError(
                f"Gateway returned {response.status_code}: {response.text}"
            )

        except httpx.RequestError as exc:
            logger.error("SMTP gateway connection error: %s", exc)
            raise EmailServiceError(f"Could not reach email gateway: {exc}") from exc

    @staticmethod
    async def send_otp_email(to: str, to_name: Optional[str], otp_code: str) -> dict:
        """Send a password-reset OTP email."""
        subject = "Your Password Reset Code"
        html_body = f"""
        <div style="font-family: Arial, sans-serif; max-width: 480px; margin: auto;">
            <h2>Password Reset Request</h2>
            <p>Hi{f' {to_name}' if to_name else ''},</p>
            <p>Use the code below to reset your password. It expires in <strong>10 minutes</strong>.</p>
            <div style="font-size: 36px; font-weight: bold; letter-spacing: 8px;
                        padding: 20px; background: #f4f4f4; text-align: center;
                        border-radius: 8px; margin: 24px 0;">
                {otp_code}
            </div>
            <p>If you did not request a password reset, please ignore this email.</p>
        </div>
        """
        text_body = (
            f"Your password reset code is: {otp_code}\n"
            "It expires in 10 minutes.\n"
            "If you did not request this, ignore this email."
        )
        return await EmailService.send(
            to=to,
            subject=subject,
            html_body=html_body,
            to_name=to_name,
            text_body=text_body,
            priority="CRITICAL",
        )

    @staticmethod
    async def send_report_email(
        to: str,
        subject: str,
        html_body: str,
        to_name: Optional[str] = None,
        text_body: Optional[str] = None,
        attachments: Optional[list] = None,
        priority: str = "LOW",
    ) -> dict:
        """
        Send a report email, optionally with file attachments.

        Each attachment must be:
            { "filename": "report.pdf", "content": "<base64>", "contentType": "application/pdf" }
        """
        return await EmailService.send(
            to=to,
            subject=subject,
            html_body=html_body,
            to_name=to_name,
            text_body=text_body,
            priority=priority,
            attachments=attachments,
        )
