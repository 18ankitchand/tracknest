"""Spending overview API backed by the current user's recorded expenses.

Daily/weekly/monthly grouping is descriptive analytics, not forecasting.
No external AI service is used and the endpoint never changes records.
"""
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.db.models import Sum
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_GET

from .models import ExpenseTransaction, MonthlyBudget


def previous_month(first):
    return (first - timedelta(days=1)).replace(day=1)


@require_GET
def spending_overview(request):
    if not request.user.is_authenticated:
        return JsonResponse({"error": "Sign in to see spending insights."}, status=401)

    today = timezone.localdate()
    first = today.replace(day=1)
    previous = previous_month(first)
    months = [first]
    for _ in range(5):
        months.append(previous_month(months[-1]))
    months.reverse()

    # Read at most the last six months; never read another user's transactions.
    expenses = ExpenseTransaction.objects.filter(
        user=request.user, kind="expense", date__gte=months[0], date__lte=today,
    ).values("date", "category", "amount")

    by_day = defaultdict(lambda: Decimal("0.00"))
    by_month = defaultdict(lambda: Decimal("0.00"))
    category_totals = defaultdict(lambda: Decimal("0.00"))
    current_count = 0
    last_count = 0
    for item in expenses.iterator():
        day = item["date"]
        amount = item["amount"]
        by_day[day] += amount
        by_month[day.strftime("%Y-%m")] += amount
        if day >= first:
            current_count += 1
            category_totals[item["category"]] += amount
        elif previous <= day < first:
            last_count += 1

    def daily(days):
        start = today - timedelta(days=days - 1)
        return [
            {"date": (start + timedelta(days=i)).isoformat(),
             "label": (start + timedelta(days=i)).strftime("%d %b"),
             "amount": float(by_day[start + timedelta(days=i)])}
            for i in range(days)
        ]

    monthly = [
        {"month": month.strftime("%Y-%m"), "label": month.strftime("%b %Y"),
         "amount": float(by_month[month.strftime("%Y-%m")])}
        for month in months
    ]
    current_total = by_month[first.strftime("%Y-%m")]
    previous_total = by_month[previous.strftime("%Y-%m")]
    budget = MonthlyBudget.objects.filter(user=request.user, month=first).first()
    budget_limit = budget.limit if budget and budget.is_set_by_user else None
    categories = sorted(category_totals.items(), key=lambda pair: (-pair[1], pair[0].lower()))
    return JsonResponse({
        "periods": {"7d": daily(7), "30d": daily(30), "6m": monthly},
        "month": first.strftime("%B %Y"),
        "current_total": float(current_total),
        "previous_total": float(previous_total),
        "monthly_transactions": current_count,
        "previous_transactions": last_count,
        "daily_average": float(current_total / Decimal(today.day)),
        "budget_limit": float(budget_limit) if budget_limit is not None else None,
        "budget_used_percent": float(current_total * 100 / budget_limit) if budget_limit else None,
        "top_category": {"name": categories[0][0], "amount": float(categories[0][1])} if categories else None,
        "categories": [{"name": name, "amount": float(amount)} for name, amount in categories],
    })
