"""User-owned income overview: calendar-month and day-level descriptive aggregates."""
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_GET

from .models import ExpenseTransaction
from .spending_overview import previous_month


@require_GET
def income_overview(request):
    if not request.user.is_authenticated:
        return JsonResponse({"error": "Sign in to see income insights."}, status=401)

    today = timezone.localdate()
    current = today.replace(day=1)
    previous = previous_month(current)
    months = [current]
    for _ in range(5):
        months.append(previous_month(months[-1]))
    months.reverse()

    records = ExpenseTransaction.objects.filter(
        user=request.user, kind="income", date__gte=months[0], date__lte=today
    ).values("date", "category", "amount")

    daily = defaultdict(lambda: Decimal("0.00"))
    monthly = defaultdict(lambda: Decimal("0.00"))
    categories = defaultdict(lambda: Decimal("0.00"))
    current_count = previous_count = 0
    for record in records.iterator():
        date = record["date"]
        amount = record["amount"]
        daily[date] += amount
        monthly[date.strftime("%Y-%m")] += amount
        if date >= current:
            current_count += 1
            categories[record["category"]] += amount
        elif date >= previous:
            previous_count += 1

    def days(count):
        start = today - timedelta(days=count - 1)
        return [
            {"date": (start + timedelta(days=i)).isoformat(),
             "label": (start + timedelta(days=i)).strftime("%d %b"),
             "amount": float(daily[start + timedelta(days=i)])}
            for i in range(count)
        ]

    category_data = sorted(categories.items(), key=lambda p: (-p[1], p[0].lower()))
    current_total = monthly[current.strftime("%Y-%m")]
    previous_total = monthly[previous.strftime("%Y-%m")]
    return JsonResponse({
        "periods": {
            "7d": days(7), "30d": days(30),
            "6m": [{"month": month.strftime("%Y-%m"), "label": month.strftime("%b %Y"),
                    "amount": float(monthly[month.strftime("%Y-%m")])} for month in months],
        },
        "current_total": float(current_total),
        "previous_total": float(previous_total),
        "monthly_transactions": current_count,
        "previous_transactions": previous_count,
        "daily_average": float(current_total / Decimal(today.day)),
        "top_category": {"name": category_data[0][0], "amount": float(category_data[0][1])}
                        if category_data else None,
        "categories": [{"name": name, "amount": float(amount)}
                       for name, amount in category_data],
    })
