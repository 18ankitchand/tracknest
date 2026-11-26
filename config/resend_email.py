"""Django email backend using Resend's HTTPS API.

Configured only by server-side RESEND_API_KEY and RESEND_FROM_EMAIL.
Never logs API keys or sends directly from the browser.
"""
import json
import logging
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend
from django.core.mail.backends.smtp import EmailBackend as SMTPEmailBackend

logger = logging.getLogger(__name__)


class ResendEmailBackend(BaseEmailBackend):
    """Send plain-text Django EmailMessage instances over Resend HTTPS."""

    def send_messages(self, email_messages):
        if not email_messages:
            return 0
        key = getattr(settings, "RESEND_API_KEY", "")
        sender = getattr(settings, "RESEND_FROM_EMAIL", "")
        if not key or not sender:
            if self.fail_silently:
                return 0
            raise ValueError("Resend is missing its API key or verified sender address")
        sent = 0
        for message in email_messages:
            try:
                recipients = message.recipients()
                if not recipients:
                    continue
                payload = {
                    "from": sender,
                    "to": recipients,
                    "subject": message.subject,
                    "text": message.body,
                }
                # Keep formatting compatible with Django's standard send_mail().
                request = Request(
                    "https://api.resend.com/emails",
                    data=json.dumps(payload).encode("utf-8"),
                    headers={
                        "Authorization": "Bearer " + key,
                        "Content-Type": "application/json",
                        "User-Agent": "TrackNest/1.0",
                    },
                    method="POST",
                )
                with urlopen(request, timeout=12) as response:
                    data = json.loads(response.read(8192))
                    if response.status != 200 and response.status != 201:
                        raise OSError("Resend rejected the email")
                    if not isinstance(data, dict) or not data.get("id"):
                        raise OSError("Resend returned no message ID")
                sent += 1
            except HTTPError as error:
                logger.error("Resend email API rejected a request (HTTP %s)", error.code)
                if not self.fail_silently:
                    raise OSError("Resend email API rejected the message") from None
            except (URLError, OSError, ValueError, TimeoutError) as error:
                logger.error("Resend email send failed: %s", type(error).__name__)
                if not self.fail_silently:
                    raise OSError("Resend email delivery request failed") from None
        return sent
