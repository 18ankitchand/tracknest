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
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST
from .models import Profile, MonthlyBudget, ExpenseTransaction

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
    return {"id": tx.pk, "date": tx.date.isoformat(), "desc": tx.description, "type": tx.kind, "category": tx.category, "amount": float(tx.amount)}

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
    return JsonResponse({"limit": float(budget.limit), "spent": float(spent), "locked": spent >= budget.limit, "transactions": [serialize_tx(t) for t in txs]})

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
        budget.limit = value
        budget.save(update_fields=["limit"])
    return JsonResponse({"limit": float(value), "spent": float(monthly_spent(request.user, month))})

@require_POST
def add_financial_transaction(request):
    if not request.user.is_authenticated:
        return JsonResponse({"error": "Sign in required."}, status=401)
    data = payload(request)
    kind = data.get("type")
    description = str(data.get("desc", "")).strip()
    category = str(data.get("category", "")).strip()
    try:
        amount = Decimal(str(data.get("amount", "")))
        if not amount.is_finite() or amount <= 0 or amount.as_tuple().exponent < -2 or amount > Decimal("9999999999.99"):
            raise ValueError()
    except (InvalidOperation, ValueError):
        return JsonResponse({"error": "Enter a valid positive amount (two decimal places maximum)."}, status=400)
    if kind not in ("income", "expense") or not description or len(description) > 200 or not category or len(category) > 60:
        return JsonResponse({"error": "Enter a valid transaction type, description, and category."}, status=400)
    today = timezone.localdate()
    month = month_start(today)
    with transaction.atomic():
        budget = get_budget(request.user, month)
        budget = MonthlyBudget.objects.select_for_update().get(pk=budget.pk)
        spent = monthly_spent(request.user, month)
        if kind == "expense" and spent + amount > budget.limit:
            return JsonResponse({"error": f"Expense rejected. Remaining monthly budget: Nrs {budget.limit - spent}. No additional expense was recorded.", "locked": spent >= budget.limit}, status=409)
        tx = ExpenseTransaction.objects.create(user=request.user, date=today, description=description, category=category, kind=kind, amount=amount)
        alert_queued = False
        if kind == "expense" and spent + amount >= budget.limit and not budget.limit_alert_sent and settings.EMAIL_BACKEND != "django.core.mail.backends.console.EmailBackend":
            budget.limit_alert_sent = True
            budget.save(update_fields=["limit_alert_sent"])
            email = request.user.email
            limit = budget.limit
            budget_id = budget.pk

            def notify_after_commit():
                try:
                    send_limit_email(email, limit, month)
                except Exception:
                    # Sending mail is independent of saving the expense.
                    # Leave the notification eligible for a future retry.
                    logger.exception("TrackNest budget email delivery failed for budget %s", budget_id)
                    MonthlyBudget.objects.filter(pk=budget_id).update(limit_alert_sent=False)

            transaction.on_commit(notify_after_commit)
            alert_queued = True
    return JsonResponse({"transaction": serialize_tx(tx), "alert_queued": alert_queued}, status=201)
