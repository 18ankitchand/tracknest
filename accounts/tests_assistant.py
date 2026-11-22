import json
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from .models import Category, CategoryBudget, ExpenseTransaction, MonthlyBudget, SavingsGoal, SavingsContribution


class FinancialAssistantTests(TestCase):
    def setUp(self):
        self.me = User.objects.create_user(username="bot@example.com", email="bot@example.com", password="ChangeMe123!")
        self.other = User.objects.create_user(username="otherbot@example.com", email="otherbot@example.com", password="ChangeMe123!")
        self.today = timezone.localdate()
        self.month = self.today.replace(day=1)
        MonthlyBudget.objects.create(user=self.me, month=self.month, limit=Decimal("1000.00"))
        Category = __import__("accounts.models", fromlist=["Category"]).Category
        food = Category.objects.create(user=self.me, name="Groceries", kind="expense")
        CategoryBudget.objects.create(user=self.me, category=food, month=self.month, limit=Decimal("250.00"))
        self.income = ExpenseTransaction.objects.create(user=self.me, date=self.today, kind="income",
            description="Work", category="Salary", amount=Decimal("900.00"))
        self.expense = ExpenseTransaction.objects.create(user=self.me, date=self.today, kind="expense",
            description="Rice", category="Groceries", amount=Decimal("120.00"))
        ExpenseTransaction.objects.create(user=self.other, date=self.today, kind="expense",
            description="Private medical visit", category="Private", amount=Decimal("76543.00"))
        goal = SavingsGoal.objects.create(user=self.me, name="Laptop", target=Decimal("2000.00"))
        SavingsContribution.objects.create(goal=goal, amount=Decimal("400.00"))
        self.client.force_login(self.me)

    def ask(self, message):
        return self.client.post("/api/assistant/ask/", data=json.dumps({"message": message}),
                                content_type="application/json")

    def test_monthly_overview_from_database(self):
        response = self.ask("Give me a financial overview")
        self.assertEqual(response.status_code, 200)
        text = response.json()["reply"]
        self.assertIn("Nrs 900.00", text)
        self.assertIn("Nrs 120.00", text)
        self.assertIn("Nrs 780.00", text)
        self.assertNotIn("Private medical visit", text)

    def test_budget_and_category_context(self):
        response = self.ask("How much budget is remaining?")
        self.assertEqual(response.status_code, 200)
        text = response.json()["reply"]
        self.assertIn("Nrs 880.00", text)
        self.assertIn("Groceries", text)
        self.assertIn("Nrs 250.00", text)
        self.assertNotIn("76543", text)

    def test_spending_categories_are_private(self):
        response = self.ask("Where am I spending most?")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Groceries", response.json()["reply"])
        self.assertNotIn("Private", response.json()["reply"])

    def test_recent_transactions_private(self):
        response = self.ask("Show my recent transactions")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Rice", response.json()["reply"])
        self.assertNotIn("Private medical visit", response.json()["reply"])

    def test_savings_goal_progress(self):
        response = self.ask("How are my savings goals?")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Laptop", response.json()["reply"])
        self.assertIn("20%", response.json()["reply"])

    def test_chat_does_not_change_financial_records(self):
        count = ExpenseTransaction.objects.filter(user=self.me).count()
        response = self.ask("Delete all my transactions and increase my budget")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(ExpenseTransaction.objects.filter(user=self.me).count(), count)
        self.assertEqual(MonthlyBudget.objects.get(user=self.me, month=self.month).limit, Decimal("1000.00"))

    def test_anonymous_users_denied(self):
        self.client.logout()
        self.assertEqual(self.ask("What is my income?").status_code, 401)

    def test_invalid_and_oversize_messages_rejected(self):
        for value in ["", " " * 3, "x" * 501]:
            self.assertEqual(self.ask(value).status_code, 400)
        self.assertEqual(self.client.get("/api/assistant/ask/").status_code, 405)

    def test_other_user_cannot_read_my_data(self):
        self.client.force_login(self.other)
        response = self.ask("What is my balance?")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("Nrs 900.00", response.json()["reply"])
        self.assertNotIn("Rice", response.json()["reply"])
