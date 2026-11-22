"""Regression tests for database-driven Spending Overview and privacy."""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from .models import ExpenseTransaction, MonthlyBudget


class SpendingOverviewTests(TestCase):
    def setUp(self):
        self.user=User.objects.create_user(username="spend@example.com",email="spend@example.com",password="ExamplePass123!")
        self.other=User.objects.create_user(username="other-spend@example.com",email="other-spend@example.com",password="ExamplePass123!")
        self.today=timezone.localdate()
        self.current=self.today.replace(day=1)
        self.previous=self.current-timedelta(days=1)
        self.client.force_login(self.user)

    def expense(self,user,when,amount,category="Food",kind="expense"):
        return ExpenseTransaction.objects.create(user=user,date=when,amount=Decimal(amount),
            kind=kind,description="Test transaction",category=category,payment_method="Cash")

    def test_current_previous_months_daily_series_and_categories(self):
        self.expense(self.user,self.today,"100.00","Food")
        self.expense(self.user,self.today,"50.00","Transport")
        self.expense(self.user,self.previous,"80.00","Food")
        self.expense(self.user,self.today,"500.00","Salary",kind="income")
        self.expense(self.other,self.today,"9999.00","Private")
        MonthlyBudget.objects.create(user=self.user,month=self.current,limit=Decimal("500"),is_set_by_user=True)
        response=self.client.get("/api/finance/spending-overview/")
        self.assertEqual(response.status_code,200)
        data=response.json()
        self.assertEqual(data["current_total"],150.0)
        self.assertEqual(data["previous_total"],80.0)
        self.assertEqual(data["monthly_transactions"],2)
        self.assertEqual(data["previous_transactions"],1)
        self.assertEqual(data["budget_used_percent"],30.0)
        self.assertAlmostEqual(data["daily_average"],150/self.today.day)
        self.assertEqual(data["top_category"],{"name":"Food","amount":100.0})
        self.assertEqual([x["name"] for x in data["categories"]],["Food","Transport"])
        self.assertEqual(len(data["periods"]["7d"]),7)
        self.assertEqual(len(data["periods"]["30d"]),30)
        self.assertEqual(len(data["periods"]["6m"]),6)
        self.assertEqual(data["periods"]["7d"][-1]["date"],self.today.isoformat())
        self.assertEqual(data["periods"]["7d"][-1]["amount"],150.0)
        self.assertEqual(data["periods"]["6m"][-1]["amount"],150.0)
        self.assertEqual(data["periods"]["6m"][-2]["amount"],80.0)
        self.assertNotIn("Private",str(data))
        self.client.force_login(self.other)
        other=self.client.get("/api/finance/spending-overview/").json()
        self.assertEqual(other["current_total"],9999.0)
        self.assertNotIn("Food",str(other))

    def test_empty_dataset_and_months_with_zero_spending(self):
        data=self.client.get("/api/finance/spending-overview/").json()
        self.assertEqual(data["current_total"],0.0)
        self.assertEqual(data["monthly_transactions"],0)
        self.assertIsNone(data["top_category"])
        self.assertIsNone(data["budget_used_percent"])
        self.assertEqual(data["categories"],[])
        self.assertTrue(all(row["amount"]==0 for row in data["periods"]["6m"]))
        self.assertTrue(all(row["amount"]==0 for row in data["periods"]["30d"]))

    def test_only_authenticated_read_only_access(self):
        self.assertEqual(self.client.post("/api/finance/spending-overview/").status_code,405)
        self.client.logout()
        self.assertEqual(self.client.get("/api/finance/spending-overview/").status_code,401)

    def test_expenses_page_contains_interactive_insights(self):
        response=self.client.get("/expenses/")
        self.assertEqual(response.status_code,200)
        for marker in ["tnSpendingTrendChart","tnSpendingCategoryChart",
                       "tnInsightsMonthTotal","tnInsightsTopCategory",
                       'data-tn-spending-period="7d"','data-tn-spending-period="6m"']:
            self.assertContains(response,marker)
        self.assertNotContains(response,'id="expensePageChart"')
