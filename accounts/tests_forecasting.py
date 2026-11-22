"""Tests for the academic Time Series Forecasting algorithm and API."""
from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from .forecasting import (
    fit_linear_regression, forecast_from_months, rolling_origin_mae, shift_month,
)
from .models import ExpenseTransaction


class LinearRegressionUnitTests(TestCase):
    def test_ols_fits_known_linear_history(self):
        intercept, slope=fit_linear_regression([100,200,300,400,500])
        self.assertAlmostEqual(intercept,100.0)
        self.assertAlmostEqual(slope,100.0)
        result=forecast_from_months([100,200,300,400,500],current_total=50)
        self.assertEqual(result["status"],"ready")
        self.assertEqual(result["forecast_current"],600.0)
        self.assertEqual(result["forecast_next"],700.0)
        self.assertEqual(result["mae"],0.0)
        self.assertEqual(result["backtest_count"],2)

    def test_negative_forecasts_clamped_at_zero(self):
        result=forecast_from_months([500,400,300,200,100],current_total=25)
        self.assertEqual(result["status"],"ready")
        self.assertEqual(result["forecast_current"],25.0)
        self.assertEqual(result["forecast_next"],0.0)

    def test_insufficient_history_never_invents_prediction(self):
        for history in ([],[100],[100,200],[0,10,0,20,0]):
            result=forecast_from_months(history)
            self.assertEqual(result["status"],"insufficient_data")
            self.assertIsNone(result["forecast_current"])
            self.assertIsNone(result["forecast_next"])
        self.assertEqual(forecast_from_months([100,200,300])["backtest_count"],0)
        self.assertIsNone(forecast_from_months([100,200,300])["mae"])

    def test_month_shift_across_year_boundary(self):
        self.assertEqual(shift_month(date(2026,1,1),-1),date(2025,12,1))
        self.assertEqual(shift_month(date(2026,12,1),1),date(2027,1,1))


class ExpenseForecastEndpointTests(TestCase):
    def setUp(self):
        self.user=User.objects.create_user(username="forecast@example.com",email="forecast@example.com",password="TestForecast123!")
        self.other=User.objects.create_user(username="otherforecast@example.com",email="otherforecast@example.com",password="TestForecast123!")
        self.month=timezone.localdate().replace(day=1)
        self.client.force_login(self.user)

    def transaction(self,user,month,amount,kind="expense"):
        return ExpenseTransaction.objects.create(
            user=user,date=month,description="Recorded monthly spending",
            category="Utilities" if kind=="expense" else "Salary",
            kind=kind,amount=Decimal(str(amount)),payment_method="Cash",
        )

    def test_three_completed_months_create_real_user_only_predictions(self):
        for offset,amount in [(-3,100),(-2,200),(-1,300)]:
            self.transaction(self.user,shift_month(self.month,offset),amount)
        self.transaction(self.user,self.month,50)
        self.transaction(self.user,self.month,800,kind="income")
        self.transaction(self.other,shift_month(self.month,-1),10000)
        response=self.client.get("/api/finance/forecast/")
        self.assertEqual(response.status_code,200)
        result=response.json()
        self.assertEqual(result["status"],"ready")
        self.assertEqual(result["training_months"],3)
        self.assertEqual(result["active_training_months"],3)
        self.assertEqual(result["forecast_current"],400.0)
        self.assertEqual(result["forecast_next"],500.0)
        self.assertEqual(result["current_month_spent"],50.0)
        self.assertEqual(result["history"][-1]["amount"],300.0)
        self.assertEqual(len(result["history"]),3)
        self.assertIsNone(result["mae"])
        self.client.force_login(self.other)
        private=self.client.get("/api/finance/forecast/").json()
        self.assertEqual(private["status"],"insufficient_data")
        self.assertNotIn("400.0",str(private))

    def test_current_month_only_is_not_trained_or_predicted(self):
        self.transaction(self.user,self.month,120)
        data=self.client.get("/api/finance/forecast/").json()
        self.assertEqual(data["status"],"insufficient_data")
        self.assertEqual(data["current_month_spent"],120.0)
        self.assertIsNone(data["forecast_current"])
        self.assertIsNone(data["forecast_next"])

    def test_fills_gap_months_with_zero_and_does_not_use_income(self):
        for offset,amount in [(-5,100),(-3,200),(-1,300)]:
            self.transaction(self.user,shift_month(self.month,offset),amount)
        self.transaction(self.user,shift_month(self.month,-2),999,kind="income")
        data=self.client.get("/api/finance/forecast/").json()
        self.assertEqual(data["status"],"ready")
        self.assertEqual([x["amount"] for x in data["history"]],[100,0,200,0,300])
        self.assertEqual(data["training_months"],5)
        self.assertEqual(data["backtest_count"],2)
        self.assertIsNotNone(data["mae"])

    def test_access_controls_and_get_only(self):
        self.assertEqual(self.client.post("/api/finance/forecast/").status_code,405)
        self.client.logout()
        self.assertEqual(self.client.get("/api/finance/forecast/").status_code,401)

    def test_forecast_page_displays_trained_model_information(self):
        response=self.client.get("/forecast/")
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'id="tnForecastNextPrediction"')
        self.assertContains(response,'id="tnForecastMAE"')
        self.assertContains(response,'id="forecastChart"')
        self.assertContains(response,'Ordinary Least Squares Linear Regression')
        self.assertNotContains(response,"demonstration multiplier")
