import json
import re
import logging
from django.contrib.auth import authenticate, login, logout, password_validation
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.core.mail import send_mail
from django.conf import settings
from django.utils import timezone
from decimal import Decimal, InvalidOperation
from datetime import date
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST
from .models import Profile, MonthlyBudget, ExpenseTransaction, CategoryBudget, UserPreference
from .premium_api import evaluate_budget_alerts, category_spending

logger = logging.getLogger(__name__)

def payload(request):
 try:
  data=json.loads(request.body)
  return data if isinstance(data,dict) else {}
 except (ValueError,UnicodeDecodeError):
  return {}

def identity(user):
 return {'name':user.first_name,'email':user.email,'phone':user.profile.phone}

@ensure_csrf_cookie
@require_GET
def home(request):
 return render(request,'index.html')

@require_POST
def register(request):
 data=payload(request)
 name=str(data.get('name','')).strip()
 email=str(data.get('email','')).strip().lower()
 phone=str(data.get('phone','')).strip()
 password=data.get('password','')
 confirm=data.get('confirm_password','')
 if not name or len(name)>150 or not email or len(email)>254 or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email):
  return JsonResponse({'error':'Enter a valid name and email.'},status=400)
 if not re.fullmatch(r'\+?[0-9][0-9 -]{6,18}',phone):
  return JsonResponse({'error':'Enter a valid phone number.'},status=400)
 if password != confirm:
  return JsonResponse({'error':'Passwords do not match.'},status=400)
 candidate=User(username=email,email=email,first_name=name)
 try: password_validation.validate_password(password,candidate)
 except ValidationError as exc: return JsonResponse({'error':' '.join(exc.messages)},status=400)
 if User.objects.filter(username__iexact=email).exists():
  return JsonResponse({'error':'This email is already registered.'},status=400)
 try:
  with transaction.atomic():
   user=User.objects.create_user(username=email,email=email,password=password,first_name=name)
   Profile.objects.create(user=user,phone=phone)
 except IntegrityError:
  return JsonResponse({'error':'This email is already registered.'},status=400)
 login(request,user)
 return JsonResponse({'user':identity(user)},status=201)

@require_POST
def sign_in(request):
 data=payload(request)
 email=str(data.get('email','')).strip().lower()
 password=data.get('password','')
 user=authenticate(request,username=email,password=password)
 if user is None or not user.is_active:
  return JsonResponse({'error':'Invalid email or password.'},status=400)
 login(request,user)
 return JsonResponse({'user':identity(user)})

@require_POST
def sign_out(request):
 logout(request)
 return JsonResponse({'ok':True})

@require_GET
def me(request):
 if not request.user.is_authenticated:
  return JsonResponse({'user':None})
 return JsonResponse({'user':identity(request.user)})


def month_start(day):
    return day.replace(day=1)

def monthly_spent(user, month):
    return ExpenseTransaction.objects.filter(user=user, kind="expense", date__year=month.year, date__month=month.month).aggregate(total=Sum("amount"))["total"] or Decimal("0")

def get_budget(user, month):
    return MonthlyBudget.objects.get_or_create(user=user, month=month)[0]

def serialize_tx(tx):
    return {"id": tx.pk, "date": tx.date.isoformat(), "desc": tx.description, "type": tx.kind, "category": tx.category, "amount": float(tx.amount), "payment_method": tx.payment_method, "notes": tx.notes}

def send_limit_email(email, limit, month):
    send_mail(
        "TrackNest: Monthly expense limit reached",
        f"Your recorded expenses have reached your monthly limit of Nrs {limit} for {month:%B %Y}. "
        "TrackNest will not allow additional expenses for this month unless you increase your budget. "
        "This restriction applies only to expense recording in TrackNest, not external bank or card payments.",
        settings.DEFAULT_FROM_EMAIL,
        [email],
        fail_silently=False,
    )

@require_GET
def financial_state(request):
    if not request.user.is_authenticated:
        return JsonResponse({"error": "Sign in required."}, status=401)
    month = month_start(timezone.localdate())
    budget = get_budget(request.user, month)
    spent = monthly_spent(request.user, month)
    txs = ExpenseTransaction.objects.filter(user=request.user).order_by("-date", "-pk")[:500]
    email_ready = bool(request.user.email and settings.EMAIL_BACKEND == "django.core.mail.backends.smtp.EmailBackend"
                       and settings.EMAIL_HOST_USER and settings.EMAIL_HOST_PASSWORD)
    return JsonResponse({"limit": float(budget.limit), "spent": float(spent), "locked": spent >= budget.limit,
                         "email_delivery_configured": email_ready,
                         "transactions": [serialize_tx(t) for t in txs]})

@require_POST
def set_budget(request):
    if not request.user.is_authenticated:
        return JsonResponse({"error": "Sign in required."}, status=401)
    try:
        value = Decimal(str(payload(request).get("limit", "")))
        if not value.is_finite() or value <= 0 or value.as_tuple().exponent < -2 or value > Decimal("9999999999.99"):
            raise ValueError()
    except (InvalidOperation, ValueError):
        return JsonResponse({"error": "Enter a positive budget with up to two decimal places."}, status=400)
    month = month_start(timezone.localdate())
    with transaction.atomic():
        budget = get_budget(request.user, month)
        budget = MonthlyBudget.objects.select_for_update().get(pk=budget.pk)
        spent = monthly_spent(request.user, month)
        budget.limit = value
        # Moving back below the limit allows one new 100% email when reached again.
        if spent < value:
            budget.limit_alert_sent = False
            budget.save(update_fields=["limit", "limit_alert_sent"])
        else:
            budget.save(update_fields=["limit"])
        evaluate_budget_alerts(request.user, month)
        # Reaching 100% by lowering a budget must email just like adding an expense.
        alert_queued = spent >= value and queue_budget_email(request.user, budget, month)
    return JsonResponse({"limit": float(value), "spent": float(spent), "alert_queued": alert_queued})


def validate_transaction_fields(data, default_date=None):
    """Parse and validate user input on the server, including the accounting date."""
    kind = data.get("type")
    description = str(data.get("desc", "")).strip()
    category = str(data.get("category", "")).strip()
    try:
        amount = Decimal(str(data.get("amount", "")))
        if not amount.is_finite() or amount <= 0 or amount.as_tuple().exponent < -2 or amount > Decimal("9999999999.99"):
            raise ValueError()
    except (InvalidOperation, ValueError):
        return None, "Enter a valid positive amount with up to two decimal places."

    if kind not in ("income", "expense") or not description or len(description) > 200 or not category or len(category) > 60:
        return None, "Enter a valid transaction type, description, and category."

    raw_date = data.get("date")
    if raw_date is None and default_date is not None:
        tx_date = default_date
    elif raw_date is None:
        tx_date = timezone.localdate()
    else:
        try:
            if not isinstance(raw_date, str) or len(raw_date) != 10 or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw_date):
                raise ValueError()
            tx_date = date.fromisoformat(raw_date)
        except ValueError:
            return None, "Enter a valid transaction date (YYYY-MM-DD)."

    if tx_date > timezone.localdate() or tx_date < date(2000, 1, 1):
        return None, "Choose a transaction date between 2000-01-01 and today."

    payment_method = str(data.get("payment_method", "Cash")).strip()
    notes = str(data.get("notes", "")).strip()
    if payment_method not in ("Cash", "Bank Transfer", "Card", "Mobile Wallet", "Other") or len(notes) > 1000:
        return None, "Choose a valid payment method and limit notes to 1,000 characters."
    return {
        "kind": kind,
        "description": description,
        "category": category,
        "amount": amount,
        "date": tx_date,
        "payment_method": payment_method,
        "notes": notes,
    }, None


def queue_budget_email(user, budget, month):
    """Mark a current-month alert and send after commit. Reset the flag on delivery failure."""
    if month != month_start(timezone.localdate()) or budget.limit_alert_sent or not user.email:
        return False
    if settings.EMAIL_BACKEND == "django.core.mail.backends.console.EmailBackend":
        return False
    pref, _ = UserPreference.objects.get_or_create(user=user)
    if not pref.email_alerts_enabled:
        return False

    budget.limit_alert_sent = True
    budget.save(update_fields=["limit_alert_sent"])
    email = user.email
    limit = budget.limit
    budget_id = budget.pk

    def notify():
        try:
            send_limit_email(email, limit, month)
        except Exception:
            logger.exception("TrackNest budget email delivery failed for budget %s", budget_id)
            MonthlyBudget.objects.filter(pk=budget_id).update(limit_alert_sent=False)

    transaction.on_commit(notify)
    return True


@require_POST
def add_financial_transaction(request):
    if not request.user.is_authenticated:
        return JsonResponse({"error": "Sign in required."}, status=401)

    fields, error = validate_transaction_fields(payload(request))
    if error:
        return JsonResponse({"error": error}, status=400)

    month = month_start(fields["date"])
    with transaction.atomic():
        budget = get_budget(request.user, month)
        budget = MonthlyBudget.objects.select_for_update().get(pk=budget.pk)
        spent = monthly_spent(request.user, month)
        if fields["kind"] == "expense" and spent + fields["amount"] > budget.limit:
            return JsonResponse(
                {"error": f"Expense rejected. Remaining budget for {month:%B %Y}: Nrs {max(Decimal('0'), budget.limit - spent)}. No expense was recorded."},
                status=409,
            )
        if fields["kind"] == "expense":
            category_budget = CategoryBudget.objects.select_for_update().filter(
                user=request.user, month=month, category__name__iexact=fields["category"]
            ).first()
            if category_budget:
                recorded_category = category_spending(request.user, category_budget.category, month)
                if recorded_category + fields["amount"] > category_budget.limit:
                    return JsonResponse({"error":
                        f"Expense rejected: {fields['category']} budget has only Nrs {max(Decimal('0'), category_budget.limit - recorded_category)} remaining."},
                        status=409)
        tx = ExpenseTransaction.objects.create(user=request.user, **fields)
        evaluate_budget_alerts(request.user, month)
        alert_queued = (
            fields["kind"] == "expense"
            and spent < budget.limit <= spent + fields["amount"]
            and queue_budget_email(request.user, budget, month)
        )
    return JsonResponse({"transaction": serialize_tx(tx), "alert_queued": alert_queued}, status=201)


@require_POST
def edit_financial_transaction(request, transaction_id):
    if not request.user.is_authenticated:
        return JsonResponse({"error": "Sign in required."}, status=401)

    with transaction.atomic():
        existing = (
            ExpenseTransaction.objects.select_for_update()
            .filter(pk=transaction_id, user=request.user)
            .first()
        )
        if existing is None:
            return JsonResponse({"error": "Transaction not found."}, status=404)

        fields, error = validate_transaction_fields(payload(request), default_date=existing.date)
        if error:
            return JsonResponse({"error": error}, status=400)

        old_month = month_start(existing.date)
        new_month = month_start(fields["date"])
        months = sorted({old_month, new_month})
        # Create absent budgets before acquiring locks, in stable month order.
        for month in months:
            get_budget(request.user, month)
        budgets = {
            budget.month: budget for budget in
            MonthlyBudget.objects.select_for_update().filter(user=request.user, month__in=months).order_by("month")
        }
        old_spent = monthly_spent(request.user, old_month)
        new_spent = monthly_spent(request.user, new_month) if new_month != old_month else old_spent
        old_contribution = existing.amount if existing.kind == "expense" else Decimal("0")
        new_contribution = fields["amount"] if fields["kind"] == "expense" else Decimal("0")

        if new_month == old_month:
            revised_old = old_spent - old_contribution + new_contribution
            revised_new = revised_old
        else:
            revised_old = old_spent - old_contribution
            revised_new = new_spent + new_contribution

        # If a budget was lowered below spending already recorded, still permit
        # neutral edits or corrections that reduce the amount overspent.
        if new_contribution and revised_new > budgets[new_month].limit and revised_new > new_spent:
            return JsonResponse(
                {"error": f"Edit rejected: the new expense exceeds the {new_month:%B %Y} budget."},
                status=409,
            )

        if new_contribution:
            category_budget = CategoryBudget.objects.select_for_update().filter(
                user=request.user, month=new_month, category__name__iexact=fields["category"]
            ).first()
            if category_budget:
                current_category = category_spending(request.user, category_budget.category, new_month)
                previous_category = (old_contribution if old_month == new_month and
                    existing.category.casefold() == fields["category"].casefold() else Decimal("0"))
                new_category_total = current_category - previous_category + new_contribution
                if new_category_total > category_budget.limit and new_category_total > current_category:
                    return JsonResponse({"error": "Edit rejected: category spending limit exceeded."}, status=409)

        for attr, value in fields.items():
            setattr(existing, attr, value)
        existing.save(update_fields=list(fields))
        evaluate_budget_alerts(request.user, old_month)
        if new_month != old_month:
            evaluate_budget_alerts(request.user, new_month)

        if revised_old < budgets[old_month].limit and budgets[old_month].limit_alert_sent:
            budgets[old_month].limit_alert_sent = False
            budgets[old_month].save(update_fields=["limit_alert_sent"])
        if new_month != old_month and revised_new < budgets[new_month].limit and budgets[new_month].limit_alert_sent:
            budgets[new_month].limit_alert_sent = False
            budgets[new_month].save(update_fields=["limit_alert_sent"])

        alert_queued = (
            bool(new_contribution)
            and new_spent < budgets[new_month].limit <= revised_new
            and queue_budget_email(request.user, budgets[new_month], new_month)
        )

    return JsonResponse({"transaction": serialize_tx(existing), "alert_queued": alert_queued})


@require_POST
def delete_financial_transaction(request, transaction_id):
    if not request.user.is_authenticated:
        return JsonResponse({"error": "Sign in required."}, status=401)

    with transaction.atomic():
        existing = (
            ExpenseTransaction.objects.select_for_update()
            .filter(pk=transaction_id, user=request.user)
            .first()
        )
        if existing is None:
            return JsonResponse({"error": "Transaction not found."}, status=404)

        budget = get_budget(request.user, month_start(existing.date))
        budget = MonthlyBudget.objects.select_for_update().get(pk=budget.pk)
        old_spent = monthly_spent(request.user, month_start(existing.date))
        after_spent = old_spent - (existing.amount if existing.kind == "expense" else Decimal("0"))
        existing.delete()
        evaluate_budget_alerts(request.user, month_start(existing.date))
        if after_spent < budget.limit and budget.limit_alert_sent:
            budget.limit_alert_sent = False
            budget.save(update_fields=["limit_alert_sent"])

    return JsonResponse({"ok": True, "message": "Transaction deleted."})
