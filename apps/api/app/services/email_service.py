from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass

from apps.api.app.config import Settings, get_settings

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class EmailMessage:
    to_email: str
    subject: str
    body: str
    html: str | None = None


def build_email_layout(
    *,
    title: str,
    intro: str,
    action_url: str,
    action_text: str,
    footer: str,
) -> str:
    safe_title = _escape_html(title)
    safe_intro = _escape_html(intro)
    safe_action_url = _escape_html_attr(action_url)
    safe_action_text = _escape_html(action_text)
    safe_footer = _escape_html(footer)

    return f"""<!doctype html>
<html lang="ru">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{safe_title}</title>
  </head>
  <body style="margin:0;padding:0;background:#0f1115;font-family:Arial,Helvetica,sans-serif;color:#e8ecf1;">
    <div style="max-width:640px;margin:0 auto;padding:32px 16px;">
      <div style="background:#171b22;border:1px solid #2b3442;border-radius:20px;padding:32px;">
        <div style="font-size:28px;font-weight:700;line-height:1.2;margin-bottom:12px;color:#ffffff;">
          {safe_title}
        </div>

        <div style="font-size:16px;line-height:1.7;color:#c7d0db;margin-bottom:24px;">
          {safe_intro}
        </div>

        <div style="margin-bottom:24px;">
          <a
            href="{safe_action_url}"
            style="display:inline-block;padding:14px 22px;border-radius:12px;background:#5865f2;color:#ffffff;text-decoration:none;font-size:16px;font-weight:700;"
          >
            {safe_action_text}
          </a>
        </div>

        <div style="font-size:14px;line-height:1.7;color:#97a3b6;">
          {safe_footer}
        </div>

        <div style="margin-top:24px;padding-top:20px;border-top:1px solid #2b3442;font-size:13px;line-height:1.6;color:#7f8a9d;">
          VoidRP • официальное письмо системы аккаунтов
        </div>
      </div>
    </div>
  </body>
</html>"""


class EmailService:
    def send(self, message: EmailMessage) -> None:
        raise NotImplementedError


class LoggingEmailService(EmailService):
    def send(self, message: EmailMessage) -> None:
        logger.info(
            "EMAIL OUTBOUND | to=%s | subject=%s | body=%s | html=%s",
            message.to_email,
            message.subject,
            message.body,
            bool(message.html),
        )


class ResendEmailService(EmailService):
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.api_key = self.settings.resend_api_key
        self.email_from = self.settings.email_from
        self.api_url = "https://api.resend.com/emails"

    def send(self, message: EmailMessage) -> None:
        if not self.api_key:
            raise RuntimeError("RESEND_API_KEY is not configured")

        payload = {
            "from": self.email_from,
            "to": [message.to_email],
            "subject": message.subject,
            "text": message.body,
        }

        if message.html:
            payload["html"] = message.html

        request = urllib.request.Request(
            self.api_url,
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "voidrp-account-backend/0.1",
            },
        )

        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                response_body = response.read().decode("utf-8", errors="replace")
                logger.info(
                    "RESEND EMAIL SENT | to=%s | subject=%s | status=%s | body=%s",
                    message.to_email,
                    message.subject,
                    response.status,
                    response_body,
                )
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            logger.exception(
                "RESEND EMAIL FAILED | to=%s | subject=%s | status=%s | body=%s",
                message.to_email,
                message.subject,
                exc.code,
                error_body,
            )
            raise RuntimeError(f"Failed to send email via Resend: HTTP {exc.code}") from exc


def _escape_html(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _escape_html_attr(value: str) -> str:
    return _escape_html(value).replace("'", "&#39;")