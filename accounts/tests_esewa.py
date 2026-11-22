import base64
import json
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase, override_settings
from django.utils import timezone

from .models import EsewaPayment, ExpenseTransaction, MonthlyBudget


@override_settings(
    ESEWA_SANDBOX_READY=True,
    ESEWA_PRODUCT_CODE="EPAYTEST",
    ESEWA_SECRET_KEY="fake-local-test-secret",
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
class EsewaSandboxTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="payer@example.com", email="payer@example.com", password="TempPass123!")
        self.other = User.objects.create_user(username="otherpayer@example.com", email="otherpayer@example.com", password="TempPass123!")
        self.month = timezone.localdate().replace(day=1)
        self.client.force_login(self.user)

    def post(self, path, values):
        return self.client.post(path, json.dumps(values), content_type="application/json")

    def configure_budget(self, value="100"):
        result = self.post("/api/finance/budget/", {"limit": value})
        self.assertEqual(result.status_code, 200)

    def start(self, value="60.00"):
        return self.post("/api/payments/esewa/start/", {
            "description": "Utility bill (test merchant)",
            "category": "Utilities",
            "amount": value,
        })

    def verified_payload(self, payment):
        return {
            "product_code": "EPAYTEST",
            "transaction_uuid": payment.transaction_uuid,
            "total_amount": f"{payment.amount:.2f}",
            "status": "COMPLETE", "ref_id": "SANDBOX-TEST-REFERENCE",
        }

    def test_new_user_must_set_budget_before_transactions_or_payment(self):
        state = self.client.get("/api/finance/state/").json()
        self.assertFalse(state["budget_configured"])
        self.assertEqual(self.start().status_code, 409)
        income = self.post("/api/finance/transactions/", {
            "type": "income", "desc": "Salary", "category": "Salary", "amount": "200",
        })
        self.assertEqual(income.status_code, 409)
        self.configure_budget("100")
        self.assertTrue(self.client.get("/api/finance/state/").json()["budget_configured"])
        self.assertEqual(self.start().status_code, 200)

    def test_pending_reservation_blocks_overspending(self):
        self.configure_budget()
        first = self.start("80")
        self.assertEqual(first.status_code, 200)
        self.assertEqual(self.start("30").status_code, 409)
        expense = self.post("/api/finance/transactions/", {
            "type": "expense", "desc": "Groceries", "category": "Food", "amount": "30"
        })
        self.assertEqual(expense.status_code, 409)
        self.assertEqual(ExpenseTransaction.objects.filter(user=self.user).count(), 0)

    def test_unverified_checkout_does_not_create_expense(self):
        self.configure_budget()
        result = self.start("50")
        self.assertEqual(result.status_code, 200)
        payment = EsewaPayment.objects.get(user=self.user)
        self.assertEqual(payment.status, "PENDING")
        self.assertEqual(ExpenseTransaction.objects.filter(user=self.user).count(), 0)
        response = self.client.get(result.json()["checkout_url"])
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Sandbox")

    def test_verified_complete_records_expense_once_and_emails_at_limit(self):
        self.configure_budget()
        self.assertEqual(self.start("100").status_code, 200)
        payment = EsewaPayment.objects.get(user=self.user)
        verified = self.verified_payload(payment)
        with patch("accounts.esewa.status_from_esewa", return_value=verified):
            with self.captureOnCommitCallbacks(execute=True):
                response = self.post(f"/api/payments/esewa/{payment.transaction_uuid}/verify/", {})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["complete"])
        self.assertEqual(ExpenseTransaction.objects.filter(user=self.user).count(), 1)
        tx = ExpenseTransaction.objects.get(user=self.user)
        self.assertEqual(tx.amount, Decimal("100.00"))
        self.assertEqual(tx.payment_method, "eSewa (Sandbox)")
        self.assertEqual(tx.esewa_payment.pk, payment.pk)
        self.assertEqual(mail.outbox[-1].to, ["payer@example.com"])
        with patch("accounts.esewa.status_from_esewa", return_value=verified):
            response2 = self.post(f"/api/payments/esewa/{payment.transaction_uuid}/verify/", {})
        self.assertTrue(response2.json()["complete"])
        self.assertEqual(ExpenseTransaction.objects.filter(user=self.user).count(), 1)
        self.assertEqual(self.start("1").status_code, 409)
        self.assertEqual(self.post(f"/api/finance/transactions/{tx.id}/delete/", {}).status_code, 409)

    def test_forged_success_redirect_rejected(self):
        self.configure_budget()
        self.start()
        payment = EsewaPayment.objects.get(user=self.user)
        forged = {
            "transaction_uuid": payment.transaction_uuid,
            "product_code": "EPAYTEST", "total_amount": "60.00", "status": "COMPLETE",
            "transaction_code": "FAKE",
            "signed_field_names": "transaction_code,status,total_amount,transaction_uuid,product_code,signed_field_names",
            "signature": "FORGED",
        }
        encoded = base64.b64encode(json.dumps(forged).encode()).decode()
        response = self.client.get("/payments/esewa/success/", {"data": encoded})
        self.assertContains(response, "Invalid or mismatched", status_code=200)
        self.assertEqual(ExpenseTransaction.objects.filter(user=self.user).count(), 0)

    def test_user_cannot_verify_another_users_payment(self):
        self.configure_budget()
        self.start()
        payment = EsewaPayment.objects.get(user=self.user)
        self.client.force_login(self.other)
        result = self.post(f"/api/payments/esewa/{payment.transaction_uuid}/verify/", {})
        self.assertEqual(result.status_code, 404)

    @override_settings(ESEWA_SANDBOX_READY=False)
    def test_disabled_payment_gateway_does_not_accept_checkouts(self):
        self.configure_budget()
        self.assertEqual(self.start().status_code, 503)

    def test_checkout_status_mismatch_does_not_record_payment(self):
        self.configure_budget()
        self.start()
        payment = EsewaPayment.objects.get(user=self.user)
        with patch("accounts.esewa.status_from_esewa", side_effect=ValueError("mismatch")):
            response = self.post(f"/api/payments/esewa/{payment.transaction_uuid}/verify/", {})
        self.assertFalse(response.json()["complete"])
        self.assertEqual(ExpenseTransaction.objects.filter(user=self.user).count(), 0)
