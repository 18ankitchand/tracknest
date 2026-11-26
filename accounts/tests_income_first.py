"""Income-first budgeting and in-app income notification regression tests."""
import json
from decimal import Decimal
from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from .models import ExpenseTransaction, MonthlyBudget, TrackNestNotification


class IncomeFirstTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="income-first@example.test", email="income-first@example.test",
            password="SafePassword123!",
        )
        self.other = User.objects.create_user(
            username="other-income@example.test", email="other-income@example.test",
            password="SafePassword123!",
        )
        self.month = timezone.localdate().replace(day=1)
        self.client.force_login(self.user)

    def post(self, path, data):
        return self.client.post(path, json.dumps(data), content_type="application/json")

    def income(self, amount, category="Salary"):
        return self.post("/api/finance/transactions/", {
            "type": "income", "desc": "Monthly income", "category": category,
            "amount": amount, "date": timezone.localdate().isoformat(),
        })

    def test_income_precedes_budget_and_has_in_app_notification_without_email(self):
        self.assertEqual(self.post("/api/finance/budget/", {"limit": "500"}).status_code, 409)
        result = self.income("500")
        self.assertEqual(result.status_code, 201)
        self.assertEqual(self.client.get("/api/finance/state/").json()["monthly_income"], 500)
        notification = TrackNestNotification.objects.get(user=self.user)
        self.assertIn("Nrs 500.00", notification.title)
        self.assertIn("Salary", notification.message)
        self.assertEqual(notification.level, "info")
        self.assertEqual(self.post("/api/finance/budget/", {"limit": "500"}).status_code, 200)

    def test_budget_cap_aggregates_income_and_is_private(self):
        self.assertEqual(self.income("500").status_code, 201)
        self.assertEqual(self.income("200", "Freelancing").status_code, 201)
        ExpenseTransaction.objects.create(
            user=self.other, date=self.month, kind="income",
            description="Other user's income", category="Salary", amount=Decimal("10000"),
        )
        response = self.post("/api/finance/budget/", {"limit": "700.01"})
        self.assertEqual(response.status_code, 409)
        self.assertIn("700.00", response.json()["error"])
        self.assertEqual(self.post("/api/finance/budget/", {"limit": "700"}).status_code, 200)
        self.assertEqual(TrackNestNotification.objects.filter(user=self.user).count(), 2)

    def test_expense_requires_budget_but_income_does_not(self):
        self.assertEqual(self.income("100").status_code, 201)
        response = self.post("/api/finance/transactions/", {
            "type": "expense", "desc": "Food", "category": "Groceries", "amount": "1",
        })
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.post("/api/finance/budget/", {"limit": "80"}).status_code, 200)
        response = self.post("/api/finance/transactions/", {
            "type": "expense", "desc": "Food", "category": "Groceries", "amount": "1",
        })
        self.assertEqual(response.status_code, 201)

    def test_reducing_income_cannot_break_existing_budget(self):
        self.assertEqual(self.income("200").status_code, 201)
        self.assertEqual(self.post("/api/finance/budget/", {"limit": "150"}).status_code, 200)
        tx = ExpenseTransaction.objects.get(user=self.user, kind="income")
        changed = self.post(f"/api/finance/transactions/{tx.id}/edit/", {
            "type": "income", "desc": "Correction", "category": "Salary", "amount": "100",
            "date": timezone.localdate().isoformat(),
        })
        self.assertEqual(changed.status_code, 409)
        self.assertEqual(self.post(f"/api/finance/transactions/{tx.id}/delete/", {}).status_code, 409)
        self.assertEqual(ExpenseTransaction.objects.get(pk=tx.id).amount, Decimal("200"))

    def test_income_notification_is_owner_only(self):
        self.assertEqual(self.income("50").status_code, 201)
        self.client.force_login(self.other)
        response = self.client.get("/api/notifications/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["notifications"], [])
