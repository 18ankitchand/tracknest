from django.conf import settings
from django.db import models
from django.core.validators import MinValueValidator
from decimal import Decimal

class Profile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile")
    phone = models.CharField(max_length=20)

class MonthlyBudget(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    month = models.DateField()  # First day of month
    limit = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("50000.00"), validators=[MinValueValidator(Decimal("0.01"))])
    limit_alert_sent = models.BooleanField(default=False)
    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "month"], name="unique_user_budget_month")]

class ExpenseTransaction(models.Model):
    TYPE_CHOICES = [("income", "Income"), ("expense", "Expense")]
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    date = models.DateField()
    description = models.CharField(max_length=200)
    kind = models.CharField(max_length=7, choices=TYPE_CHOICES)
    category = models.CharField(max_length=60)
    amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    class Meta:
        indexes = [models.Index(fields=["user", "date"])]
