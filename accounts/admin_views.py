from decimal import Decimal

from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import get_user_model
from django.db.models import Count, Q, Sum
from django.db.models.functions import Coalesce
from django.shortcuts import render

from .models import ExpenseTransaction


@staff_member_required
# This page is for trusted administrators only, never regular users.
def overview(request):
    User = get_user_model()
    users = (
        User.objects.annotate(
            expense_count=Count("expensetransaction", filter=Q(expensetransaction__kind="expense")),
            expense_total=Coalesce(
                Sum("expensetransaction__amount", filter=Q(expensetransaction__kind="expense")),
                Decimal("0.00"),
            ),
        )
        .order_by("-date_joined")
    )
    totals = ExpenseTransaction.objects.filter(kind="expense").aggregate(
        expense_records=Count("id"),
        total_expenses=Coalesce(Sum("amount"), Decimal("0.00")),
    )
    return render(request, "admin/overview.html", {
        "title": "TrackNest overview",
        "registered_users": User.objects.filter(is_staff=False).count(),
        "all_accounts": User.objects.count(),
        "expense_records": totals["expense_records"],
        "total_expenses": totals["total_expenses"],
        "users": users,
        "site_header": admin_site_header(),
    })


def admin_site_header():
    return "TrackNest administration"
