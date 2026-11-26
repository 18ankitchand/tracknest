"""HTTP mail transport tests; no real Resend API calls are made."""
import json
from unittest.mock import patch
from django.core.mail import send_mail
from django.test import TestCase, override_settings

BACKEND = "config.resend_email.ResendEmailBackend"


class ResendEmailBackendTests(TestCase):
    @override_settings(
        EMAIL_BACKEND=BACKEND,
        RESEND_API_KEY="test-api-key",
        RESEND_FROM_EMAIL="TrackNest <alerts@example.org>",
        DEFAULT_FROM_EMAIL="TrackNest <alerts@example.org>",
    )
    def test_send_mail_uses_resend_https_api(self):
        response = self._mock_response()
        with patch("config.resend_email.urlopen", return_value=response) as request_mock:
            result = send_mail("Budget 91%", "Critical budget warning", None, ["user@example.org"])
        self.assertEqual(result, 1)
        request = request_mock.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.resend.com/emails")
        self.assertEqual(request.get_method(), "POST")
        payload = json.loads(request.data)
        self.assertEqual(payload["to"], ["user@example.org"])
        self.assertEqual(payload["subject"], "Budget 91%")
        self.assertEqual(payload["text"], "Critical budget warning")
        self.assertEqual(payload["from"], "TrackNest <alerts@example.org>")

    @staticmethod
    def _mock_response():
        from unittest.mock import MagicMock
        response = MagicMock()
        response.status = 200
        response.read.return_value = b'{"id":"test-message-id"}'
        response.__enter__.return_value = response
        return response

    @override_settings(
        EMAIL_BACKEND=BACKEND, RESEND_API_KEY="", RESEND_FROM_EMAIL="",
    )
    def test_missing_configuration_fails_closed(self):
        with self.assertRaises(ValueError):
            send_mail("Test", "body", None, ["user@example.org"])

    @override_settings(
        EMAIL_BACKEND=BACKEND, RESEND_API_KEY="test-api-key",
        RESEND_FROM_EMAIL="TrackNest <alerts@example.org>",
    )
    def test_http_failure_does_not_claim_message_sent(self):
        from urllib.error import HTTPError
        error = HTTPError("https://api.resend.com/emails", 403, "Forbidden", {}, None)
        with patch("config.resend_email.urlopen", side_effect=error):
            with self.assertRaises(OSError):
                send_mail("Test", "body", None, ["user@example.org"])

    @override_settings(
        EMAIL_BACKEND=BACKEND, RESEND_API_KEY="test-api-key",
        RESEND_FROM_EMAIL="TrackNest <alerts@example.org>",
    )
    def test_financial_state_detects_resend(self):
        from accounts.views import email_transport_configured
        self.assertTrue(email_transport_configured())
