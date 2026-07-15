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
        from django.core.mail import EmailMultiAlternatives
        from asgiref.sync import sync_to_async
        import base64

        to_address = f"{to_name} <{to}>" if to_name else to
        text_content = text_body or "Please view this email in an HTML-compatible client."

        msg = EmailMultiAlternatives(
            subject=subject,
            body=text_content,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[to_address],
        )
        msg.attach_alternative(html_body, "text/html")

        if attachments:
            for att in attachments:
                # Expects { "filename": "...", "content": "<base64>", "contentType": "..." }
                file_content = base64.b64decode(att["content"])
                msg.attach(att["filename"], file_content, att["contentType"])

        try:
            # send() returns the number of successfully delivered messages (1 or 0)
            sent = await sync_to_async(msg.send)(fail_silently=False)
            if sent == 0:
                raise EmailServiceError("Email backend returned 0 messages sent.")
            return {"status": "sent"}
        except Exception as exc:
            logger.error("SMTP sending error: %s", exc)
            raise EmailServiceError(f"Could not send email: {exc}") from exc

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
