from decimal import Decimal

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User
from django.db.models import Count, Q, Sum
from django.db.models.functions import Coalesce

from .models import ExpenseTransaction, MonthlyBudget, Profile, EsewaPayment


class ProfileInline(admin.StackedInline):
    model = Profile
    can_delete = False
    extra = 0


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "phone")
    search_fields = ("user__username", "user__email", "phone")
    list_select_related = ("user",)


admin.site.unregister(User)


@admin.register(User)
class TrackerUserAdmin(UserAdmin):
    inlines = (ProfileInline,)
    list_display = ("username", "first_name", "email", "expense_count", "expense_total", "is_staff", "date_joined")
    list_filter = ("is_staff", "is_active", "date_joined")
    search_fields = ("username", "first_name", "email")

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(
            _expense_count=Count("expensetransaction", filter=Q(expensetransaction__kind="expense")),
            _expense_total=Coalesce(
                Sum("expensetransaction__amount", filter=Q(expensetransaction__kind="expense")),
                Decimal("0.00"),
            ),
        )

    @admin.display(description="Expense records", ordering="_expense_count")
    def expense_count(self, obj):
        return obj._expense_count

    @admin.display(description="Total expenses (Nrs)", ordering="_expense_total")
    def expense_total(self, obj):
        return f"{obj._expense_total:,.2f}"


@admin.register(ExpenseTransaction)
class ExpenseTransactionAdmin(admin.ModelAdmin):
    list_display = ("user", "date", "kind", "category", "description", "amount")
    list_filter = ("kind", "category", "date")
    search_fields = ("user__email", "description", "category")
    list_select_related = ("user",)
    date_hierarchy = "date"
    readonly_fields = ("user", "date", "kind", "category", "description", "amount")

    def has_add_permission(self, request):
        # Avoid bypassing budget enforcement from the admin UI.
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(MonthlyBudget)
class MonthlyBudgetAdmin(admin.ModelAdmin):
    list_display = ("user", "month", "limit", "limit_alert_sent")
    list_filter = ("month", "limit_alert_sent")
    search_fields = ("user__email",)
    list_select_related = ("user",)
    readonly_fields = ("user", "month", "limit", "limit_alert_sent")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(EsewaPayment)
class EsewaPaymentAdmin(admin.ModelAdmin):
    """Read-only provider audit data; expenses must be created through verification."""
    list_display = ("transaction_uuid", "user", "amount", "status", "is_sandbox", "created_at", "reference_code")
    list_filter = ("status", "is_sandbox", "created_at")
    search_fields = ("transaction_uuid", "reference_code", "user__email", "description")
    list_select_related = ("user", "expense")
    readonly_fields = (
        "user", "transaction_uuid", "description", "category", "amount", "month",
        "status", "reference_code", "expense", "is_sandbox", "created_at", "verified_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
