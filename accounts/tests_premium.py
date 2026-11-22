import json
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase, override_settings
from django.utils import timezone

from .models import (
    Category, CategoryBudget, ExpenseTransaction, MonthlyBudget,
    SavingsContribution, SavingsGoal, TrackNestNotification, UserPreference,
)


class PremiumFinanceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="premium@example.com", email="premium@example.com",
            password="StartPass123!", first_name="Premium User",
        )
        self.other = User.objects.create_user(
            username="private@example.com", email="private@example.com",
            password="StartPass123!",
        )
        self.month = timezone.localdate().replace(day=1)
        self.budget = MonthlyBudget.objects.create(
            user=self.user, month=self.month, limit=Decimal("100.00"), is_set_by_user=True
        )
        self.category = Category.objects.create(user=self.user, kind="expense", name="Groceries")
        self.client.force_login(self.user)

    def post(self, url, data):
        return self.client.post(url, data=json.dumps(data), content_type="application/json")

    def expense(self, amount):
        return self.post("/api/finance/transactions/", {
            "type": "expense", "desc": "Food", "category": "Groceries",
            "amount": amount, "date": timezone.localdate().isoformat(),
            "payment_method": "Cash", "notes": "weekly shopping",
        })

    def test_category_budgets_block_overspending(self):
        response = self.post("/api/category-budgets/change/", {
            "category_id": self.category.pk, "month": self.month.isoformat(),
            "limit": "50.00",
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.expense("35.00").status_code, 201)
        self.assertEqual(self.expense("20.00").status_code, 409)
        self.assertEqual(ExpenseTransaction.objects.filter(user=self.user).count(), 1)

    def test_authenticated_category_isolation(self):
        category = Category.objects.create(user=self.other, kind="expense", name="Private")
        response = self.post("/api/category-budgets/change/", {
            "category_id": category.pk, "month": self.month.isoformat(),
            "limit": "20.00",
        })
        self.assertEqual(response.status_code, 400)
        response = self.post("/api/categories/change/", {
            "action": "delete", "id": category.pk,
        })
        self.assertEqual(response.status_code, 404)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_threshold_alerts_are_not_repeated(self):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.expense("80.00")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(TrackNestNotification.objects.filter(user=self.user).count(), 1)
        self.assertEqual(len(mail.outbox), 1)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.expense("10.00")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(TrackNestNotification.objects.filter(user=self.user).count(), 2)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.expense("10.00")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(TrackNestNotification.objects.filter(user=self.user).count(), 3)
        self.assertEqual(self.expense("1.00").status_code, 409)

    def test_transactions_csv_filtered_and_private(self):
        ExpenseTransaction.objects.create(
            user=self.user, date=timezone.localdate(), kind="expense",
            description="=SUM(A1:A2)", category="Groceries",
            amount=Decimal("7.00"),
        )
        ExpenseTransaction.objects.create(
            user=self.other, date=timezone.localdate(), kind="income",
            description="Private entry", category="Salary",
            amount=Decimal("123.00"),
        )
        response = self.client.get("/api/finance/export.csv")
        self.assertEqual(response.status_code, 200)
        self.assertIn("\'=SUM(A1:A2)", response.content.decode())
        self.assertNotIn("Private entry", response.content.decode())

    def test_reports_pdf_download(self):
        response = self.client.get("/api/finance/export.pdf")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF"))

    def test_goal_contribution_and_owner_isolation(self):
        response = self.post("/api/goals/change/", {
            "name": "New laptop", "target": "2000.00",
        })
        self.assertEqual(response.status_code, 200)
        pk = response.json()["id"]
        self.assertEqual(self.post("/api/goals/change/", {
            "action": "contribute", "id": pk, "amount": "125.00",
        }).status_code, 200)
        self.assertEqual(SavingsContribution.objects.filter(goal_id=pk).count(), 1)
        goal = SavingsGoal.objects.create(user=self.other, name="Private", target=Decimal("1000"))
        self.assertEqual(self.post("/api/goals/change/", {
            "action": "delete", "id": goal.pk,
        }).status_code, 404)

    def test_user_preferences_persist(self):
        response = self.post("/api/preferences/change/", {
            "theme": "dark", "currency": "NPR", "email_alerts_enabled": False,
        })
        self.assertEqual(response.status_code, 200)
        pref = UserPreference.objects.get(user=self.user)
        self.assertEqual(pref.theme, "dark")
        self.assertFalse(pref.email_alerts_enabled)

    def test_mark_notification_read_cannot_access_others(self):
        notif = TrackNestNotification.objects.create(user=self.other, title="Private", message="No")
        response = self.post("/api/notifications/read/", {"id": notif.pk})
        self.assertEqual(response.status_code, 404)
        notif.refresh_from_db()
        self.assertFalse(notif.is_read)

    def test_password_change_requires_current_password(self):
        wrong = self.post("/api/profile/password/", {
            "current_password": "wrong", "new_password": "DifferentPassword42!",
        })
        self.assertEqual(wrong.status_code, 400)
        correct = self.post("/api/profile/password/", {
            "current_password": "StartPass123!", "new_password": "DifferentPassword42!",
        })
        self.assertEqual(correct.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("DifferentPassword42!"))

    def test_existing_user_data_survives_new_schema(self):
        tx = ExpenseTransaction.objects.create(
            user=self.user, date=timezone.localdate(), kind="income",
            category="Salary", amount=Decimal("100.00"),
            description="Legacy record",
        )
        self.assertEqual(tx.payment_method, "Cash")
        self.assertEqual(tx.notes, "")

    def test_email_change_requires_signed_in_confirmation_post(self):
        from django.core import signing
        token = signing.dumps(
            {"user": self.user.pk, "new_email": "new-premium@example.com"},
            salt="tracknest-email-change",
        )
        url = "/api/profile/confirm-email/?token=" + token
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "premium@example.com")
        response = self.client.post("/api/profile/confirm-email/", {"token": token})
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "new-premium@example.com")

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_email_change_sends_verification_only_to_new_address(self):
        response = self.post("/api/profile/request-email/", {
            "new_email": "new-premium@example.com",
            "current_password": "StartPass123!",
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(mail.outbox[-1].to, ["new-premium@example.com"])
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "premium@example.com")


class FinanceNavigationTests(TestCase):
    def test_every_workspace_has_a_distinct_django_route(self):
        paths = [
            "/dashboard/", "/income/", "/expenses/", "/transactions/",
            "/budgets/", "/categories/", "/reports/", "/goals/",
            "/notifications/", "/settings/", "/profile/", "/forecast/", "/advisor/",
        ]
        self.assertEqual(len(paths), len(set(paths)))
        for url in paths:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, 'id="appScreen"')
