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
    DEBUG=True,
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

    def test_pending_checkout_prevents_lowering_budget_below_reserved_amount(self):
        self.configure_budget("100")
        self.start("80")
        response = self.post("/api/finance/budget/", {"limit": "50"})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(MonthlyBudget.objects.get(user=self.user, month=self.month).limit, Decimal("100.00"))

    def test_unverified_checkout_does_not_create_expense(self):
        self.configure_budget()
        result = self.start("50")
        self.assertEqual(result.status_code, 200)
        payment = EsewaPayment.objects.get(user=self.user)
        self.assertEqual(payment.status, "PENDING")
        self.assertEqual(ExpenseTransaction.objects.filter(user=self.user).count(), 0)
        response = self.client.get(result.json()["checkout_url"])
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "eSewa Demo")

    def test_expenses_page_starts_esewa_from_save_without_separate_payment_panel(self):
        self.configure_budget("100")
        response = self.client.get("/expenses/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<select id="expenseEntryPayment"><option value="eSewa Demo">', html=False)
        self.assertContains(response, 'id="tnExpenseSubmitButton"')
        self.assertContains(response, 'Save Expense')
        self.assertContains(response, 'id="tnEsewaReviewDialog"')
        self.assertContains(response, 'Continue to Payment')
        self.assertNotContains(response, 'class="tn-esewa-box"')
        self.assertNotContains(response, 'id="tnEsewaPayments"')
        self.assertEqual(ExpenseTransaction.objects.filter(user=self.user).count(), 0)

    def test_continue_checkout_forwards_to_real_demo_gateway_without_saving_expense(self):
        self.configure_budget("100")
        response = self.start("35.00")
        self.assertEqual(response.status_code, 200)
        payment = EsewaPayment.objects.get(user=self.user)
        checkout = self.client.get(response.json()["checkout_url"])
        self.assertEqual(checkout.status_code, 200)
        self.assertContains(checkout, 'id="esewaCheckout"')
        self.assertContains(checkout, "https://rc-epay.esewa.com.np/api/epay/main/v2/form")
        self.assertContains(checkout, "requestSubmit()")
        self.assertContains(checkout, "Continue to eSewa Demo")
        self.assertEqual(payment.status, "PENDING")
        self.assertFalse(ExpenseTransaction.objects.filter(user=self.user).exists())

    def test_checkout_preserves_notes_in_verified_expense(self):
        self.configure_budget("100")
        response = self.post("/api/payments/esewa/start/", {
            "description": "Electricity bill demo",
            "category": "Utilities",
            "amount": "30.00",
            "notes": "November meter reading",
        })
        self.assertEqual(response.status_code, 200)
        payment = EsewaPayment.objects.get(user=self.user)
        self.assertEqual(payment.notes, "November meter reading")
        with patch("accounts.esewa.status_from_esewa", return_value=self.verified_payload(payment)):
            result = self.post(f"/api/payments/esewa/{payment.transaction_uuid}/verify/", {})
        self.assertTrue(result.json()["complete"])
        payment.refresh_from_db()
        self.assertIsNotNone(payment.expense)
        self.assertIn("November meter reading", payment.expense.notes)
        self.assertIn("sandbox", payment.expense.notes.lower())

    def test_oversize_notes_rejected_before_payment(self):
        self.configure_budget("100")
        response = self.post("/api/payments/esewa/start/", {
            "description": "Example",
            "category": "Utilities",
            "amount": "30.00",
            "notes": "x" * 1001,
        })
        self.assertEqual(response.status_code, 400)
        self.assertFalse(EsewaPayment.objects.filter(user=self.user).exists())

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

    def test_signed_success_callback_verifies_with_provider_before_recording(self):
        from .esewa import SIGNED_RESPONSE_FIELDS, signature
        self.configure_budget()
        self.start("60")
        payment = EsewaPayment.objects.get(user=self.user)
        provider = self.verified_payload(payment)
        fields = {
            "transaction_code": "DEMO-REF",
            "status": "COMPLETE",
            "total_amount": "60.00",
            "transaction_uuid": payment.transaction_uuid,
            "product_code": "EPAYTEST",
            "signed_field_names": SIGNED_RESPONSE_FIELDS,
        }
        signed_message = ",".join(f"{name}={fields[name]}" for name in SIGNED_RESPONSE_FIELDS.split(","))
        fields["signature"] = signature(signed_message)
        encoded = base64.b64encode(json.dumps(fields).encode()).decode()
        with patch("accounts.esewa.status_from_esewa", return_value=provider):
            response = self.client.get("/payments/esewa/success/", {"data": encoded})
        self.assertContains(response, "payment verified", status_code=200)
        self.assertEqual(ExpenseTransaction.objects.filter(user=self.user).count(), 1)

    def test_signed_success_callback_supports_numeric_total_amount(self):
        from .esewa import SIGNED_RESPONSE_FIELDS, signature
        self.configure_budget()
        self.start("60")
        payment = EsewaPayment.objects.get(user=self.user)
        provider = self.verified_payload(payment)
        fields = {
            "transaction_code": "DEMO-REF",
            "status": "COMPLETE",
            "total_amount": 60.0,
            "transaction_uuid": payment.transaction_uuid,
            "product_code": "EPAYTEST",
            "signed_field_names": SIGNED_RESPONSE_FIELDS,
        }
        signed_message = ",".join(f"{name}={fields[name]}" for name in SIGNED_RESPONSE_FIELDS.split(","))
        fields["signature"] = signature(signed_message)
        encoded = base64.b64encode(json.dumps(fields).encode()).decode()
        with patch("accounts.esewa.status_from_esewa", return_value=provider):
            response = self.client.get("/payments/esewa/success/", {"data": encoded})
        self.assertContains(response, "Payment verified", status_code=200)
        self.assertEqual(ExpenseTransaction.objects.filter(user=self.user).count(), 1)

    def test_missing_signed_callback_fields_cannot_create_expense(self):
        from .esewa import SIGNED_RESPONSE_FIELDS
        self.configure_budget()
        self.start("60")
        payment = EsewaPayment.objects.get(user=self.user)
        fields = {
            "status": "COMPLETE",
            "transaction_uuid": payment.transaction_uuid,
            "product_code": "EPAYTEST",
            "total_amount": "60.00",
            "signed_field_names": SIGNED_RESPONSE_FIELDS,
            "signature": "irrelevant",
        }
        data = base64.b64encode(json.dumps(fields).encode()).decode()
        response = self.client.get("/payments/esewa/success/", {"data": data})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(ExpenseTransaction.objects.filter(user=self.user).count(), 0)

    def test_invalid_base64_payment_callback_returns_error_not_server_exception(self):
        self.configure_budget()
        response = self.client.get("/payments/esewa/success/", {"data": "not-valid-@@"})
        self.assertEqual(response.status_code, 400)

    def test_user_cannot_verify_another_users_payment(self):
        self.configure_budget()
        self.start()
        payment = EsewaPayment.objects.get(user=self.user)
        self.client.force_login(self.other)
        result = self.post(f"/api/payments/esewa/{payment.transaction_uuid}/verify/", {})
        self.assertEqual(result.status_code, 404)

    @override_settings(DEBUG=False, ESEWA_SANDBOX_READY=True)
    def test_public_demo_is_disabled_outside_development(self):
        from .esewa import configured
        self.assertFalse(configured())
        self.configure_budget()
        self.assertEqual(self.start().status_code, 503)

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
