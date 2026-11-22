"""Regression checks for matching income overview, forecast explanations and budget guide."""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from .models import ExpenseTransaction


class IncomeOverviewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="income-overview-a", password="TestPass123!")
        self.other = User.objects.create_user(username="income-overview-b", password="TestPass123!")
        self.today = timezone.localdate()
        self.month_start = self.today.replace(day=1)
        self.previous_day = self.month_start - timedelta(days=1)
        self.client.force_login(self.user)

    def record(self, user, date, amount, category="Salary", kind="income"):
        return ExpenseTransaction.objects.create(
            user=user, kind=kind, date=date, category=category,
            description="Test entry", payment_method="Bank Transfer", amount=Decimal(amount)
        )

    def test_monthly_income_daily_series_sources_and_user_isolation(self):
        self.record(self.user, self.today, "2500.00", "Salary")
        self.record(self.user, self.today, "500.00", "Freelance")
        self.record(self.user, self.previous_day, "800.00", "Gift")
        self.record(self.user, self.today, "10000.00", "Other", kind="expense")
        self.record(self.other, self.today, "99000.00", "Private")

        response = self.client.get("/api/finance/income-overview/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["current_total"], 3000.0)
        self.assertEqual(data["previous_total"], 800.0)
        self.assertEqual(data["monthly_transactions"], 2)
        self.assertEqual(data["previous_transactions"], 1)
        self.assertAlmostEqual(data["daily_average"], 3000 / self.today.day)
        self.assertEqual(data["top_category"], {"name": "Salary", "amount": 2500.0})
        self.assertEqual([item["name"] for item in data["categories"]], ["Salary", "Freelance"])
        self.assertEqual(len(data["periods"]["7d"]), 7)
        self.assertEqual(len(data["periods"]["30d"]), 30)
        self.assertEqual(len(data["periods"]["6m"]), 6)
        self.assertEqual(data["periods"]["7d"][-1]["amount"], 3000.0)
        self.assertEqual(data["periods"]["6m"][-1]["amount"], 3000.0)
        self.assertEqual(data["periods"]["6m"][-2]["amount"], 800.0)
        self.assertNotIn("Private", str(data))

        self.client.force_login(self.other)
        other = self.client.get("/api/finance/income-overview/").json()
        self.assertEqual(other["current_total"], 99000.0)
        self.assertNotIn("Salary", str(other))

    def test_empty_data_has_zeroes_and_no_fabricated_sources(self):
        result = self.client.get("/api/finance/income-overview/").json()
        self.assertEqual(result["current_total"], 0.0)
        self.assertEqual(result["previous_total"], 0.0)
        self.assertEqual(result["monthly_transactions"], 0)
        self.assertIsNone(result["top_category"])
        self.assertEqual(result["categories"], [])
        self.assertTrue(all(item["amount"] == 0 for item in result["periods"]["6m"]))

    def test_authenticated_read_only_endpoint(self):
        self.assertEqual(self.client.post("/api/finance/income-overview/").status_code, 405)
        self.client.logout()
        self.assertEqual(self.client.get("/api/finance/income-overview/").status_code, 401)

    def test_income_page_contains_separate_interactive_dashboard(self):
        response = self.client.get("/income/")
        self.assertEqual(response.status_code, 200)
        for needle in (
            'id="tnIncomeInsightTitle"', 'id="tnIncomeInsightsMonthTotal"',
            'id="tnIncomeTrendChart"', 'id="tnIncomeTrendFallback"',
            'id="tnIncomeCategoryChart"', 'id="tnIncomeCategoryList"',
            'data-tn-income-period="30d"', 'data-tn-income-period="6m"',
            "Understand where your income comes from",
        ):
            self.assertContains(response, needle)
        self.assertNotContains(response, 'id="incomePageChart"')

    def test_budget_page_shows_four_thresholds_and_forecast_page_explains_model(self):
        budget = self.client.get("/budgets/")
        self.assertEqual(budget.status_code, 200)
        for needle in ('id="tnBudgetProtectionStatus"', 'id="tnBudgetProtectionBar"',
                       'data-budget-threshold="warning"', 'data-budget-threshold="critical"',
                       'data-budget-threshold="limit"', '80%–below 90%', '100% or above'):
            self.assertContains(budget, needle)
        forecast = self.client.get("/forecast/")
        self.assertEqual(forecast.status_code, 200)
        for needle in ('id="tnForecastModelState"', 'id="tnForecastTrend"',
                       'id="tnForecastTrainingSummary"', 'id="tnForecastValidation"',
                       'id="tnForecastChartNote"', 'Past spending vs. predicted spending',
                       'Collect monthly totals', 'Fit Linear Regression', 'Forecast and evaluate'):
            self.assertContains(forecast, needle)
