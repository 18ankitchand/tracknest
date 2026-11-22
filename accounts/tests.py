from decimal import Decimal
from datetime import date

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import ExpenseTransaction, MonthlyBudget, Profile


class AdminOverviewTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="owner@example.com", email="owner@example.com", password="SafePassword123!")
        self.other = User.objects.create_user(username="other@example.com", email="other@example.com", password="SafePassword123!")
        self.staff = User.objects.create_user(username="admin@example.com", email="admin@example.com", password="SafePassword123!", is_staff=True, is_superuser=True)
        Profile.objects.create(user=self.owner, phone="9812345678")
        ExpenseTransaction.objects.create(user=self.owner, date=date(2026, 11, 1), description="Food", kind="expense", category="Food", amount=Decimal("125.50"))
        ExpenseTransaction.objects.create(user=self.owner, date=date(2026, 11, 2), description="Job", kind="income", category="Salary", amount=Decimal("900.00"))
        ExpenseTransaction.objects.create(user=self.other, date=date(2026, 11, 3), description="Travel", kind="expense", category="Travel", amount=Decimal("200.00"))

    def test_overview_requires_staff(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("admin_overview"))
        self.assertEqual(response.status_code, 302)

    def test_admin_overview_totals_and_per_user(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse("admin_overview"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["registered_users"], 2)
        self.assertEqual(response.context["all_accounts"], 3)
        self.assertEqual(response.context["expense_records"], 2)
        self.assertEqual(response.context["total_expenses"], Decimal("325.50"))
        per_user = {u.email: u for u in response.context["users"]}
        self.assertEqual(per_user["owner@example.com"].expense_count, 1)
        self.assertEqual(per_user["owner@example.com"].expense_total, Decimal("125.50"))
        self.assertEqual(per_user["other@example.com"].expense_total, Decimal("200.00"))
        self.assertEqual(per_user["admin@example.com"].expense_total, Decimal("0.00"))

    def test_financial_state_is_private(self):
        self.client.force_login(self.owner)
        response = self.client.get("/api/finance/state/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["transactions"]), 2)
        self.assertNotIn("Travel", str(response.json()))

    def test_budget_blocks_expense_above_limit(self):
        self.client.force_login(self.owner)
        from django.utils import timezone
        month = timezone.localdate().replace(day=1)
        MonthlyBudget.objects.filter(user=self.owner).delete()
        MonthlyBudget.objects.create(user=self.owner, month=month, limit=Decimal("10.00"))
        import json
        response = self.client.post("/api/finance/transactions/", data=json.dumps({"type":"expense", "desc":"Extra", "category":"Food", "amount":"11.00"}), content_type="application/json")
        self.assertEqual(response.status_code, 409)
        self.assertFalse(ExpenseTransaction.objects.filter(description="Extra").exists())


class BudgetEmailTests(TestCase):
    def setUp(self):
        from django.utils import timezone
        self.user = User.objects.create_user(
            username="alert@example.com", email="alert@example.com", password="SafePassword123!"
        )
        self.month = timezone.localdate().replace(day=1)
        self.budget = MonthlyBudget.objects.create(
            user=self.user, month=self.month, limit=Decimal("20.00")
        )
        self.client.force_login(self.user)

    @staticmethod
    def transaction_payload(amount):
        import json
        return json.dumps({
            "type": "expense",
            "desc": "Groceries",
            "category": "Food",
            "amount": amount,
        })

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_at_limit_sends_one_email_to_registered_user(self):
        from django.core import mail
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                "/api/finance/transactions/",
                data=self.transaction_payload("20.00"),
                content_type="application/json",
            )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(ExpenseTransaction.objects.filter(user=self.user).count(), 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["alert@example.com"])
        self.budget.refresh_from_db()
        self.assertTrue(self.budget.limit_alert_sent)
        response = self.client.post(
            "/api/finance/transactions/",
            data=self.transaction_payload("1.00"),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 409)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend")
    def test_email_failure_does_not_undo_expense(self):
        from unittest.mock import patch
        with patch("accounts.views.send_limit_email", side_effect=RuntimeError("offline")):
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.post(
                    "/api/finance/transactions/",
                    data=self.transaction_payload("20.00"),
                    content_type="application/json",
                )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(ExpenseTransaction.objects.filter(user=self.user).count(), 1)
        self.budget.refresh_from_db()
        self.assertFalse(self.budget.limit_alert_sent)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.console.EmailBackend")
    def test_console_backend_does_not_claim_email_sent(self):
        response = self.client.post(
            "/api/finance/transactions/",
            data=self.transaction_payload("20.00"),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        self.budget.refresh_from_db()
        self.assertFalse(self.budget.limit_alert_sent)
