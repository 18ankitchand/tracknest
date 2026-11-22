"""Additional finance APIs for TrackNest's premium UI.

All queries are scoped to request.user. No API endpoint accepts a user ID.
Financial amounts are validated as Decimal values on the server.
"""
import csv
import json
import logging
from datetime import date
from decimal import Decimal, InvalidOperation
from collections import defaultdict

from django.contrib.auth import update_session_auth_hash, password_validation
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from .models import (
    Category, CategoryBudget, ExpenseTransaction, MonthlyBudget,
    Profile, SavingsGoal, SavingsContribution, TrackNestNotification, UserPreference,
)
logger = logging.getLogger(__name__)


def read_json(request):
    try:
        item = json.loads(request.body or '{}')
        return item if isinstance(item, dict) else {}
    except (ValueError, UnicodeDecodeError):
        return {}


def money(value):
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or amount <= 0 or amount > Decimal("9999999999.99") or amount.as_tuple().exponent < -2:
            raise ValueError
        return amount
    except (ValueError, InvalidOperation, TypeError):
        return None


def forbidden(request):
    if not request.user.is_authenticated:
        return JsonResponse({"error": "Please sign in."}, status=401)
    return None


def get_month(raw=None):
    current = timezone.localdate().replace(day=1)
    if not raw:
        return current
    try:
        parsed = date.fromisoformat(raw)
        if parsed.day != 1 or not date(2000, 1, 1) <= parsed <= current:
            raise ValueError
        return parsed
    except (TypeError, ValueError):
        return None


def date_filter(request):
    start, end = request.GET.get('from'), request.GET.get('to')
    try:
        start = date.fromisoformat(start) if start else None
        end = date.fromisoformat(end) if end else None
        if start and end and start > end:
            raise ValueError
        return start, end, None
    except ValueError:
        return None, None, JsonResponse({"error": "Choose a valid date range."}, status=400)


def user_transactions(request):
    qs = ExpenseTransaction.objects.filter(user=request.user)
    start, end, error = date_filter(request)
    if error:
        return None, error
    if start: qs = qs.filter(date__gte=start)
    if end: qs = qs.filter(date__lte=end)
    return qs, None


@require_GET
def analytics(request):
    problem = forbidden(request)
    if problem: return problem
    qs, error = user_transactions(request)
    if error: return error
    totals = {kind: qs.filter(kind=kind).aggregate(value=Sum("amount"))["value"] or Decimal("0") for kind in ("income", "expense")}
    months = defaultdict(lambda: {"income": Decimal("0"), "expense": Decimal("0")})
    categories = defaultdict(lambda: Decimal("0"))
    for tx in qs.values("date", "kind", "category", "amount").iterator():
        month = tx["date"].strftime("%Y-%m")
        months[month][tx["kind"]] += tx["amount"]
        if tx["kind"] == "expense":
            categories[tx["category"]] += tx["amount"]
    return JsonResponse({
        "income": float(totals["income"]), "expense": float(totals["expense"]),
        "balance": float(totals["income"] - totals["expense"]),
        "monthly": [{"month": key, "income": float(value["income"]), "expense": float(value["expense"])} for key, value in sorted(months.items())],
        "categories": [{"name": key, "amount": float(val)} for key, val in sorted(categories.items(), key=lambda item: -item[1])],
    })


def _csv_safe(value):
    text = str(value or "")
    if text.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + text
    return text


@require_GET
def export_csv(request):
    problem = forbidden(request)
    if problem: return problem
    qs, error = user_transactions(request)
    if error: return error
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="tracknest-transactions.csv"'
    response.write("\ufeff")
    writer = csv.writer(response)
    writer.writerow(["Date", "Description", "Category", "Type", "Amount (NPR)", "Payment method", "Notes"])
    for tx in qs.order_by("-date", "-id").iterator():
        writer.writerow([tx.date.isoformat(), _csv_safe(tx.description), _csv_safe(tx.category),
                         tx.kind, f"{tx.amount:.2f}", _csv_safe(tx.payment_method), _csv_safe(tx.notes)])
    return response


@require_GET
def categories_list(request):
    problem = forbidden(request)
    if problem: return problem
    return JsonResponse({"categories": [{"id": c.id, "name": c.name, "type": c.kind} for c in Category.objects.filter(user=request.user)]})


@require_POST
def categories_change(request):
    problem = forbidden(request)
    if problem: return problem
    data = read_json(request)
    action = data.get("action", "create")
    if action in ("edit", "delete"):
        cat = Category.objects.filter(user=request.user, pk=data.get("id")).first()
        if not cat: return JsonResponse({"error": "Category not found."}, status=404)
        if action == "delete":
            if cat.monthly_budgets.exists():
                return JsonResponse({"error": "Remove this category's budgets before deleting it."}, status=409)
            cat.delete()
            return JsonResponse({"ok": True})
    elif action != "create":
        return JsonResponse({"error": "Unknown action."}, status=400)
    else:
        cat = None
    kind = data.get("type")
    name = str(data.get("name", "")).strip()
    if kind not in ("income", "expense") or not name or len(name) > 60:
        return JsonResponse({"error": "Enter a category name and income/expense type."}, status=400)
    if Category.objects.filter(user=request.user, kind=kind, name__iexact=name).exclude(pk=cat.pk if cat else None).exists():
        return JsonResponse({"error": "A category with this name already exists."}, status=409)
    try:
        if cat:
            if cat.kind != kind and cat.monthly_budgets.exists():
                return JsonResponse({"error": "Remove the category budgets before changing its type."}, status=409)
            cat.name, cat.kind = name, kind
            cat.save(update_fields=["name", "kind"])
        else:
            cat = Category.objects.create(user=request.user, kind=kind, name=name)
    except IntegrityError:
        return JsonResponse({"error": "Category already exists."}, status=409)
    return JsonResponse({"id": cat.id, "name": cat.name, "type": cat.kind})


def category_spending(user, category, month):
    return ExpenseTransaction.objects.filter(user=user, kind="expense", category=category.name,
        date__year=month.year, date__month=month.month).aggregate(total=Sum("amount"))["total"] or Decimal("0")


@require_GET
def category_budget_list(request):
    problem = forbidden(request)
    if problem: return problem
    month = get_month(request.GET.get("month"))
    if not month: return JsonResponse({"error": "Invalid budget month."}, status=400)
    rows = []
    for item in CategoryBudget.objects.filter(user=request.user, month=month).select_related("category"):
        spent = category_spending(request.user, item.category, month)
        rows.append({"id": item.id, "category_id": item.category_id, "category": item.category.name,
                     "limit": float(item.limit), "spent": float(spent),
                     "remaining": float(item.limit - spent), "percentage": round(float(spent / item.limit) * 100, 1)})
    return JsonResponse({"month": month.isoformat(), "budgets": rows})


@require_POST
def category_budget_change(request):
    problem = forbidden(request)
    if problem: return problem
    data = read_json(request)
    action = data.get("action", "create")
    if action in ("edit", "delete"):
        item = CategoryBudget.objects.filter(user=request.user, pk=data.get("id")).first()
        if not item: return JsonResponse({"error": "Budget not found."}, status=404)
        if action == "delete":
            item.delete()
            return JsonResponse({"ok": True})
    elif action != "create":
        return JsonResponse({"error": "Unknown action."}, status=400)
    else: item = None
    amount = money(data.get("limit"))
    if not amount: return JsonResponse({"error": "Enter a valid positive budget."}, status=400)
    category = Category.objects.filter(user=request.user, pk=data.get("category_id"), kind="expense").first()
    month = get_month(data.get("month"))
    if not category or not month:
        return JsonResponse({"error": "Choose a valid expense category and month."}, status=400)
    if item and (item.month != month or item.category_id != category.id):
        return JsonResponse({"error": "Edit the limit only, or create another budget."}, status=400)
    if CategoryBudget.objects.filter(user=request.user, category=category, month=month).exclude(pk=item.pk if item else None).exists():
        return JsonResponse({"error": "That category already has a budget for this month."}, status=409)
    if item:
        item.limit = amount
        item.notified_level = 0
        item.save(update_fields=["limit", "notified_level"])
    else: item = CategoryBudget.objects.create(user=request.user, category=category, month=month, limit=amount)
    return JsonResponse({"id": item.pk, "limit": float(item.limit)})


@require_GET
def goals_list(request):
    problem = forbidden(request)
    if problem: return problem
    result = []
    for item in SavingsGoal.objects.filter(user=request.user).order_by("-created_at"):
        saved = item.contributions.aggregate(v=Sum("amount"))["v"] or Decimal("0")
        result.append({"id": item.id, "name": item.name, "target": float(item.target),
                       "saved": float(saved), "deadline": item.deadline.isoformat() if item.deadline else None})
    return JsonResponse({"goals": result})


@require_POST
def goals_change(request):
    problem = forbidden(request)
    if problem: return problem
    data = read_json(request)
    action = data.get("action", "create")
    goal = SavingsGoal.objects.filter(user=request.user, pk=data.get("id")).first() if action != "create" else None
    if action != "create" and not goal:
        return JsonResponse({"error": "Goal not found."}, status=404)
    if action == "delete":
        goal.delete()
        return JsonResponse({"ok": True})
    if action == "contribute":
        amount = money(data.get("amount"))
        if not amount: return JsonResponse({"error": "Enter a positive contribution."}, status=400)
        SavingsContribution.objects.create(goal=goal, amount=amount)
        # Goal contributions represent allocations, not extra expense transactions.
        return JsonResponse({"ok": True})
    if action not in ("create", "edit"):
        return JsonResponse({"error": "Unknown action."}, status=400)
    amount = money(data.get("target"))
    name = str(data.get("name", "")).strip()
    if not amount or not name or len(name) > 100:
        return JsonResponse({"error": "Enter a goal name and positive target."}, status=400)
    deadline = None
    if data.get("deadline"):
        try: deadline = date.fromisoformat(data["deadline"])
        except (TypeError, ValueError): return JsonResponse({"error": "Invalid deadline."}, status=400)
    if goal:
        goal.name, goal.target, goal.deadline = name, amount, deadline
        goal.save(update_fields=["name", "target", "deadline"])
    else: goal = SavingsGoal.objects.create(user=request.user, name=name, target=amount, deadline=deadline)
    return JsonResponse({"id": goal.id, "ok": True})


@require_GET
def notifications_list(request):
    problem = forbidden(request)
    if problem: return problem
    items = TrackNestNotification.objects.filter(user=request.user)
    return JsonResponse({"unread": items.filter(is_read=False).count(),
        "notifications": [{"id": n.id, "title": n.title, "message": n.message,
                           "level": n.level, "is_read": n.is_read, "created_at": n.created_at.isoformat()}
                          for n in items[:100]]})


@require_POST
def notifications_read(request):
    problem = forbidden(request)
    if problem: return problem
    data = read_json(request)
    qs = TrackNestNotification.objects.filter(user=request.user)
    if data.get("all") is True:
        qs.update(is_read=True)
    else:
        if not isinstance(data.get("id"), int):
            return JsonResponse({"error": "Choose a notification."}, status=400)
        if not qs.filter(pk=data["id"]).update(is_read=True):
            return JsonResponse({"error": "Notification not found."}, status=404)
    return JsonResponse({"ok": True})


@require_GET
def preference_detail(request):
    problem = forbidden(request)
    if problem: return problem
    item, _ = UserPreference.objects.get_or_create(user=request.user)
    return JsonResponse({"theme": item.theme, "currency": item.currency,
                         "email_alerts_enabled": item.email_alerts_enabled})


@require_POST
def preference_change(request):
    problem = forbidden(request)
    if problem: return problem
    data = read_json(request)
    if data.get("theme") not in ("light", "dark") or data.get("currency", "NPR") != "NPR" or not isinstance(data.get("email_alerts_enabled"), bool):
        return JsonResponse({"error": "Choose a valid theme and email notification setting. TrackNest currently records NPR only."}, status=400)
    item, _ = UserPreference.objects.get_or_create(user=request.user)
    item.theme = data["theme"]
    item.email_alerts_enabled = data["email_alerts_enabled"]
    item.save(update_fields=["theme", "email_alerts_enabled"])
    return JsonResponse({"ok": True})


@require_POST
def profile_change(request):
    problem = forbidden(request)
    if problem: return problem
    data = read_json(request)
    name = str(data.get("name", "")).strip()
    phone = str(data.get("phone", "")).strip()
    if not 1 <= len(name) <= 150 or not 7 <= len(phone) <= 20:
        return JsonResponse({"error": "Enter a valid name and phone number."}, status=400)
    user = request.user
    with transaction.atomic():
        user.first_name = name
        user.save(update_fields=["first_name"])
        profile, _ = Profile.objects.get_or_create(user=user, defaults={"phone": phone})
        profile.phone = phone
        profile.save(update_fields=["phone"])
    return JsonResponse({"ok": True, "name": user.first_name, "phone": phone})


def send_threshold_notice(user, title, message, level, send_email=True):
    TrackNestNotification.objects.create(user=user, title=title, message=message, level=level)
    pref, _ = UserPreference.objects.get_or_create(user=user)
    if not send_email or not pref.email_alerts_enabled or not user.email:
        return
    if settings.EMAIL_BACKEND == "django.core.mail.backends.console.EmailBackend":
        return
    def notify():
        try:
            send_mail(title, message, settings.DEFAULT_FROM_EMAIL, [user.email], fail_silently=False)
        except Exception:
            logger.exception("TrackNest threshold email delivery failed.")
    transaction.on_commit(notify)


def evaluate_budget_alerts(user, month):
    """Persist in-app 80/90/100% alerts at most once per threshold until spending falls."""
    if month != timezone.localdate().replace(day=1):
        return
    budget = MonthlyBudget.objects.select_for_update().filter(user=user, month=month).first()
    if budget:
        spent = ExpenseTransaction.objects.filter(user=user, kind="expense",
            date__year=month.year, date__month=month.month).aggregate(v=Sum("amount"))["v"] or Decimal("0")
        level = 100 if spent >= budget.limit else 90 if spent * 100 >= budget.limit * 90 else 80 if spent * 100 >= budget.limit * 80 else 0
        if level > budget.notified_level:
            send_threshold_notice(user, f"TrackNest budget {level}% alert",
                f"You have recorded Nrs {spent:.2f} out of Nrs {budget.limit:.2f} for {month:%B %Y}. " +
                ("Further expense recording is blocked at your limit." if level == 100 else "Review your spending in TrackNest."),
                "danger" if level == 100 else "warning",
                send_email=(level != 100))  # The pre-existing 100% email path sends the limit email.
            budget.notified_level = level
            budget.save(update_fields=["notified_level"])
        elif level < budget.notified_level:
            budget.notified_level = level
            budget.save(update_fields=["notified_level"])
    for item in CategoryBudget.objects.select_for_update().filter(user=user, month=month).select_related("category"):
        spent = category_spending(user, item.category, month)
        level = 100 if spent >= item.limit else 90 if spent*100 >= item.limit*90 else 80 if spent*100 >= item.limit*80 else 0
        if level > item.notified_level:
            send_threshold_notice(user, f"TrackNest {item.category.name} budget: {level}%",
                f"Your {item.category.name} expenses are Nrs {spent:.2f} of Nrs {item.limit:.2f} for {month:%B %Y}.",
                "danger" if level == 100 else "warning")
            item.notified_level = level
            item.save(update_fields=["notified_level"])
        elif level < item.notified_level:
            item.notified_level = level
            item.save(update_fields=["notified_level"])
