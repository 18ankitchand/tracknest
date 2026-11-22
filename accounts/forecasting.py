"""Linear Regression time-series forecasting on completed monthly expenses.

Training features: sequential month index (0, 1, ...).
Training targets: each completed calendar month's recorded expense total in NPR.
Exclude the incomplete current month to avoid training bias.
No fabricated prediction is returned when there is insufficient history.
"""
from collections import defaultdict
from datetime import date
from decimal import Decimal

from django.db.models import Sum
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_GET

from .models import ExpenseTransaction


def shift_month(first, offset):
    """Return the first day of a month offset from 'first'."""
    count = first.year * 12 + first.month - 1 + offset
    return date(count // 12, count % 12 + 1, 1)


def fit_linear_regression(targets):
    """Ordinary least squares for y = intercept + slope*x (no ML dependency)."""
    count = len(targets)
    if count < 2:
        raise ValueError("At least two completed months are necessary to fit a line.")
    xs = list(range(count))
    x_mean = sum(xs) / count
    y_mean = sum(targets) / count
    denominator = sum((x - x_mean) ** 2 for x in xs)
    slope = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, targets)) / denominator
    intercept = y_mean - slope * x_mean
    return intercept, slope


def predict(intercept, slope, index):
    # Expenses cannot be negative. This floor is a modelling constraint.
    return round(max(0.0, intercept + slope * index), 2)


def rolling_origin_mae(targets):
    """One-step-ahead historical backtests, each trained on earlier months only."""
    if len(targets) < 5:
        return None, 0
    absolute_errors = []
    # Last three periods at most; each fit has a minimum of three training rows.
    for cutoff in range(max(3, len(targets) - 3), len(targets)):
        intercept, slope = fit_linear_regression(targets[:cutoff])
        predicted = predict(intercept, slope, cutoff)
        absolute_errors.append(abs(predicted - targets[cutoff]))
    return round(sum(absolute_errors) / len(absolute_errors), 2), len(absolute_errors)


def forecast_from_months(completed_totals, current_total=0):
    """Pure helper, deterministic and separately unit-testable.

    completed_totals: chronological zero-filled *completed* month values.
    A minimum of three distinct completed months with spending is required.
    """
    totals = [float(value) for value in completed_totals]
    observed = sum(1 for value in totals if value > 0)
    sufficient = len(totals) >= 3 and observed >= 3
    if not sufficient:
        return {
            "status": "insufficient_data", "model": "Ordinary Least Squares Linear Regression",
            "training_months": len(totals), "active_training_months": observed,
            "forecast_current": None, "forecast_next": None,
            "slope_per_month": None, "mae": None, "backtest_count": 0,
            "reason": "Record expenses in at least three different completed months before forecasting.",
        }
    intercept, slope = fit_linear_regression(totals)
    mae, backtests = rolling_origin_mae(totals)
    # Do not report a projected current-month total lower than what's already spent.
    current_prediction = max(float(current_total), predict(intercept, slope, len(totals)))
    return {
        "status": "ready", "model": "Ordinary Least Squares Linear Regression",
        "training_months": len(totals), "active_training_months": observed,
        "forecast_current": round(current_prediction, 2),
        "forecast_next": predict(intercept, slope, len(totals) + 1),
        "slope_per_month": round(slope, 2),
        "mae": mae, "backtest_count": backtests, "reason": None,
    }


@require_GET
def expense_forecast(request):
    if not request.user.is_authenticated:
        return JsonResponse({"error": "Sign in to see a forecast."}, status=401)

    current_month = timezone.localdate().replace(day=1)
    # Limit to twelve full months before current month, without exposing user IDs.
    history_start = shift_month(current_month, -12)
    rows = ExpenseTransaction.objects.filter(
        user=request.user, kind="expense", date__gte=history_start
    ).values("date__year", "date__month").annotate(total=Sum("amount"))
    grouped = {
        (row["date__year"], row["date__month"]): row["total"]
        for row in rows
    }
    months = [shift_month(history_start, i) for i in range(12)]
    # Keep each month since the first recorded one, including genuine zero-spending gaps.
    start_index = next(
        (i for i, month in enumerate(months) if grouped.get((month.year, month.month), 0)),
        len(months)
    )
    relevant = months[start_index:]
    totals = [grouped.get((month.year, month.month), Decimal("0.00")) for month in relevant]
    current_spent = grouped.get((current_month.year, current_month.month), Decimal("0.00"))
    result = forecast_from_months(totals, current_spent)
    next_month = shift_month(current_month, 1)
    result.update({
        "history": [{"month": month.strftime("%Y-%m"), "label": month.strftime("%b %Y"),
                     "amount": float(amount)} for month, amount in zip(relevant, totals)],
        "current_month": current_month.strftime("%Y-%m"),
        "current_month_label": current_month.strftime("%b %Y"),
        "current_month_spent": float(current_spent),
        "next_month": next_month.strftime("%Y-%m"),
        "next_month_label": next_month.strftime("%b %Y"),
        "method_note": "Forecast is estimated from completed monthly spending using a fitted linear trend. "
                       "It cannot predict sudden events or seasonal spending reliably.",
    })
    return JsonResponse(result)
