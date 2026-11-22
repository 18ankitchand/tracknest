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
    notified_level = models.PositiveSmallIntegerField(default=0)
    is_set_by_user = models.BooleanField(default=False)
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
    payment_method = models.CharField(max_length=30, default="Cash")
    notes = models.TextField(blank=True, default="")
    class Meta:
        indexes = [models.Index(fields=["user", "date"], name="accounts_ex_user_id_fab11e_idx")]


class Category(models.Model):
    KIND_CHOICES = [("income", "Income"), ("expense", "Expense")]
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="tracknest_categories")
    name = models.CharField(max_length=60)
    kind = models.CharField(max_length=7, choices=KIND_CHOICES)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "kind", "name"], name="unique_tracknest_user_category")]
        ordering = ["kind", "name"]


class CategoryBudget(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="tracknest_category_budgets")
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="monthly_budgets")
    month = models.DateField()
    limit = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    notified_level = models.PositiveSmallIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "category", "month"], name="unique_tracknest_category_budget")]


class SavingsGoal(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="tracknest_goals")
    name = models.CharField(max_length=100)
    target = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    created_at = models.DateTimeField(auto_now_add=True)
    deadline = models.DateField(blank=True, null=True)


class SavingsContribution(models.Model):
    goal = models.ForeignKey(SavingsGoal, on_delete=models.CASCADE, related_name="contributions")
    amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    created_at = models.DateTimeField(auto_now_add=True)


class TrackNestNotification(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="tracknest_notifications")
    title = models.CharField(max_length=150)
    message = models.TextField()
    level = models.CharField(max_length=20, default="info")
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class UserPreference(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="tracknest_preferences")
    theme = models.CharField(max_length=5, choices=[("light", "Light"), ("dark", "Dark")], default="light")
    email_alerts_enabled = models.BooleanField(default=True)
    currency = models.CharField(max_length=3, default="NPR")


class EsewaPayment(models.Model):
    """eSewa ePay checkout attempt; only verified COMPLETE payments create expenses."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="esewa_payments")
    transaction_uuid = models.CharField(max_length=64, unique=True)
    description = models.CharField(max_length=200)
    category = models.CharField(max_length=60)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    month = models.DateField()
    status = models.CharField(max_length=16, default="PENDING")
    reference_code = models.CharField(max_length=80, blank=True, default="")
    expense = models.OneToOneField(ExpenseTransaction, on_delete=models.PROTECT, related_name="esewa_payment",
                                   null=True, blank=True)
    is_sandbox = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    verified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["user", "month", "status"], name="tn_esewa_user_month_status")]

