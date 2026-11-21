from decimal import Decimal
from datetime import date

from django.contrib.auth.models import User
from django.test import TestCase
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
