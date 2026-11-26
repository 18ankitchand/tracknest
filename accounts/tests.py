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
        MonthlyBudget.objects.create(user=self.owner, month=month, limit=Decimal("10.00"), is_set_by_user=True)
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
            user=self.user, month=self.month, limit=Decimal("20.00"), is_set_by_user=True
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


    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_lowering_budget_to_current_spending_emails_registered_user_once(self):
        from django.core import mail
        ExpenseTransaction.objects.create(
            user=self.user, date=self.month, kind="expense",
            description="Bills", category="Utilities", amount=Decimal("15.00"),
        )
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                "/api/finance/budget/",
                data='{"limit":"15.00"}', content_type="application/json",
            )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["alert_queued"])
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["alert@example.com"])
        self.assertIn("limit reached", mail.outbox[0].subject.lower())
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                "/api/finance/budget/",
                data='{"limit":"15.00"}', content_type="application/json",
            )
        self.assertFalse(response.json()["alert_queued"])
        self.assertEqual(len(mail.outbox), 1)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_email_rearms_if_budget_is_raised_then_reached_again(self):
        from django.core import mail
        ExpenseTransaction.objects.create(
            user=self.user, date=self.month, kind="expense",
            description="Bills", category="Utilities", amount=Decimal("15.00"),
        )
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post("/api/finance/budget/", data='{"limit":"15.00"}',
                             content_type="application/json")
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post("/api/finance/budget/", data='{"limit":"20.00"}',
                             content_type="application/json")
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post("/api/finance/budget/", data='{"limit":"15.00"}',
                                        content_type="application/json")
        self.assertTrue(response.json()["alert_queued"])
        self.assertEqual(len(mail.outbox), 2)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.console.EmailBackend")
    def test_unconfigured_mail_does_not_claim_alert_delivered(self):
        ExpenseTransaction.objects.create(
            user=self.user, date=self.month, kind="expense",
            description="Bills", category="Utilities", amount=Decimal("15.00"),
        )
        response = self.client.post("/api/finance/budget/", data='{"limit":"15.00"}',
                                    content_type="application/json")
        self.assertFalse(response.json()["alert_queued"])
        self.assertFalse(MonthlyBudget.objects.get(pk=self.budget.pk).limit_alert_sent)
        state = self.client.get("/api/finance/state/")
        self.assertFalse(state.json()["email_delivery_configured"])


    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend",
        EMAIL_HOST_USER="",
        EMAIL_HOST_PASSWORD="",
    )
    def test_missing_smtp_credentials_does_not_queue_email(self):
        response = self.client.post(
            "/api/finance/transactions/",
            data=self.transaction_payload("20.00"),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertFalse(response.json()["alert_queued"])
        self.budget.refresh_from_db()
        self.assertFalse(self.budget.limit_alert_sent)
        self.assertEqual(ExpenseTransaction.objects.filter(user=self.user).count(), 1)
        blocked = self.client.post(
            "/api/finance/transactions/",
            data=self.transaction_payload("1.00"),
            content_type="application/json",
        )
        self.assertEqual(blocked.status_code, 409)




class EmailDeliveryDiagnosticTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="mailtest@example.com", email="mailtest@example.com",
            password="SafePassword123!"
        )
        self.client.force_login(self.user)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.console.EmailBackend")
    def test_unconfigured_mail_shows_actionable_error(self):
        result = self.client.post("/api/finance/email/test/", content_type="application/json")
        self.assertEqual(result.status_code, 503)
        self.assertIn("not configured", result.json()["error"])

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend",
        EMAIL_HOST="smtp.gmail.com", EMAIL_HOST_USER="test@example.com",
        EMAIL_HOST_PASSWORD="not-a-real-password",
    )
    def test_email_probe_sends_to_registered_user_and_is_throttled(self):
        from unittest.mock import patch
        from django.core.cache import cache
        cache.clear()
        with patch("accounts.views.send_mail", return_value=1) as sender:
            first = self.client.post("/api/finance/email/test/", content_type="application/json")
            second = self.client.post("/api/finance/email/test/", content_type="application/json")
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 429)
        self.assertEqual(sender.call_count, 1)
        self.assertEqual(sender.call_args.args[3], ["mailtest@example.com"])

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend",
        EMAIL_HOST="smtp.gmail.com", EMAIL_HOST_USER="test@example.com",
        EMAIL_HOST_PASSWORD="not-a-real-password",
    )
    def test_email_probe_reports_backend_failure_without_touching_finances(self):
        from unittest.mock import patch
        from django.core.cache import cache
        cache.clear()
        with patch("accounts.views.send_mail", side_effect=OSError("SMTP unavailable")):
            result = self.client.post("/api/finance/email/test/", content_type="application/json")
        self.assertEqual(result.status_code, 503)
        self.assertFalse(MonthlyBudget.objects.filter(user=self.user).exists())
        self.assertFalse(ExpenseTransaction.objects.filter(user=self.user).exists())



class TransactionManagementTests(TestCase):
    def setUp(self):
        from django.utils import timezone
        self.user = User.objects.create_user(
            username="editor@example.com", email="editor@example.com", password="SafePassword123!"
        )
        self.other = User.objects.create_user(
            username="other-editor@example.com", email="other-editor@example.com", password="SafePassword123!"
        )
        self.today = timezone.localdate()
        self.month = self.today.replace(day=1)
        self.budget = MonthlyBudget.objects.create(user=self.user, month=self.month, limit=Decimal("100.00"), is_set_by_user=True)
        self.item = ExpenseTransaction.objects.create(
            user=self.user, date=self.today, description="Market", kind="expense",
            category="Groceries", amount=Decimal("40.00")
        )
        self.client.force_login(self.user)

    def post_json(self, path, data):
        import json
        return self.client.post(path, data=json.dumps(data), content_type="application/json")

    def edit_url(self, item=None):
        return f"/api/finance/transactions/{(item or self.item).pk}/edit/"

    def delete_url(self, item=None):
        return f"/api/finance/transactions/{(item or self.item).pk}/delete/"

    def test_delete_own_expense_and_refresh_budget(self):
        self.budget.limit_alert_sent = True
        self.budget.save(update_fields=["limit_alert_sent"])
        response = self.post_json(self.delete_url(), {})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(ExpenseTransaction.objects.filter(pk=self.item.pk).exists())
        self.budget.refresh_from_db()
        self.assertFalse(self.budget.limit_alert_sent)

    def test_cannot_delete_or_edit_another_users_transaction(self):
        record = ExpenseTransaction.objects.create(
            user=self.other, date=self.today, description="Other", kind="expense",
            category="Food", amount=Decimal("25.00")
        )
        self.assertEqual(self.post_json(self.delete_url(record), {}).status_code, 404)
        response = self.post_json(self.edit_url(record), {
            "type": "income", "desc": "Changed", "category": "Salary",
            "amount": "20.00", "date": self.today.isoformat(),
        })
        self.assertEqual(response.status_code, 404)
        record.refresh_from_db()
        self.assertEqual(record.description, "Other")

    def test_anonymous_user_cannot_delete(self):
        self.client.logout()
        self.assertEqual(self.post_json(self.delete_url(), {}).status_code, 401)

    def test_add_transaction_with_selected_date(self):
        from datetime import timedelta
        previous = self.today - timedelta(days=1)
        response = self.post_json("/api/finance/transactions/", {
            "type": "income", "desc": "Salary", "category": "Salary",
            "amount": "250.00", "date": previous.isoformat(),
        })
        self.assertEqual(response.status_code, 201)
        self.assertTrue(ExpenseTransaction.objects.filter(
            user=self.user, date=previous, description="Salary"
        ).exists())

    def test_reject_future_and_invalid_dates(self):
        from datetime import timedelta
        for value in [(self.today + timedelta(days=1)).isoformat(), "2026-02-30"]:
            response = self.post_json("/api/finance/transactions/", {
                "type": "income", "desc": "Salary", "category": "Salary",
                "amount": "25.00", "date": value,
            })
            self.assertEqual(response.status_code, 400)

    def test_edit_date_between_months_and_check_new_month_budget(self):
        from datetime import timedelta
        previous = self.month - timedelta(days=1)
        old = self.item.date
        response = self.post_json(self.edit_url(), {
            "type": "expense", "desc": "Market corrected", "category": "Groceries",
            "amount": "40.00", "date": previous.isoformat(),
        })
        self.assertEqual(response.status_code, 200)
        self.item.refresh_from_db()
        self.assertEqual(self.item.date, previous)
        self.assertNotEqual(self.item.date, old)

    def test_edit_cannot_exceed_budget(self):
        response = self.post_json(self.edit_url(), {
            "type": "expense", "desc": "Too much", "category": "Groceries",
            "amount": "101.00", "date": self.today.isoformat(),
        })
        self.assertEqual(response.status_code, 409)
        self.item.refresh_from_db()
        self.assertEqual(self.item.amount, Decimal("40.00"))

    def test_edit_reducing_spending_when_budget_was_lowered(self):
        self.budget.limit = Decimal("30.00")
        self.budget.save(update_fields=["limit"])
        response = self.post_json(self.edit_url(), {
            "type": "expense", "desc": "Corrected", "category": "Groceries",
            "amount": "35.00", "date": self.today.isoformat(),
        })
        self.assertEqual(response.status_code, 200)
        self.item.refresh_from_db()
        self.assertEqual(self.item.amount, Decimal("35.00"))
