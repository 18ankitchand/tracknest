"""eSewa ePay v2 sandbox checkout for a TrackNest merchant.

Only real status-check COMPLETE results create an expense. Never store wallet
credentials, and never claim TrackNest can stop independent external payments.
"""
import base64
import binascii
import hashlib
import hmac
import json
import logging
import uuid
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

from django.conf import settings
from django.db import transaction
from django.db.models import Sum
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from .models import EsewaPayment, ExpenseTransaction, MonthlyBudget, CategoryBudget
from .views import monthly_spent, get_budget, queue_budget_email
from .premium_api import evaluate_budget_alerts, category_spending, send_critical_expense_reminder

logger = logging.getLogger(__name__)
FORM_URL = "https://rc-epay.esewa.com.np/api/epay/main/v2/form"
STATUS_URL = "https://rc.esewa.com.np/api/epay/transaction/status/"
SIGNED_RESPONSE_FIELDS = "transaction_code,status,total_amount,transaction_uuid,product_code,signed_field_names"


def money(value):
    try:
        n = Decimal(str(value).replace(",", ""))
        if not n.is_finite() or n <= 0 or n > Decimal("9999999999.99") or n.as_tuple().exponent < -2:
            raise ValueError()
        return n.quantize(Decimal("0.01"))
    except (ValueError, InvalidOperation, TypeError):
        return None


def configured():
    # eSewa UAT is deliberately test-only, including on an explicitly
    # opted-in hosted showcase. Real production merchant payments are not
    # implemented here.
    return bool(
        settings.ESEWA_SANDBOX_READY
        and (settings.DEBUG or getattr(settings, "ESEWA_HOSTED_TEST_ENABLED", False))
        and settings.ESEWA_PRODUCT_CODE == "EPAYTEST"
    )


def signature(message):
    return base64.b64encode(
        hmac.new(settings.ESEWA_SECRET_KEY.encode(), message.encode(), hashlib.sha256).digest()
    ).decode("ascii")


def pending_reserved(user, month, category=None, excluding=None):
    qs = EsewaPayment.objects.filter(
        user=user, month=month, status="PENDING",
        created_at__gte=timezone.now() - timedelta(minutes=15)
    )
    if category is not None:
        qs = qs.filter(category__iexact=category)
    if excluding:
        qs = qs.exclude(pk=excluding)
    return qs.aggregate(value=Sum("amount"))["value"] or Decimal("0")


def normalize_result(result):
    return isinstance(result, dict) and result.get("status") == "COMPLETE"


def status_from_esewa(payment):
    # Destination is static and HTTPS; no user-controlled URL or host.
    query = urlencode({
        "product_code": settings.ESEWA_PRODUCT_CODE,
        "total_amount": f"{payment.amount:.2f}",
        "transaction_uuid": payment.transaction_uuid,
    })
    request = Request(STATUS_URL + "?" + query, headers={"Accept": "application/json"})
    with urlopen(request, timeout=10) as response:
        if response.status != 200:
            raise ValueError("Payment verification service unavailable")
        raw = response.read(8193)
        if len(raw) > 8192:
            raise ValueError("Invalid payment status response")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("Invalid status result")
    if (data.get("transaction_uuid") != payment.transaction_uuid
            or data.get("product_code") != settings.ESEWA_PRODUCT_CODE
            or money(data.get("total_amount")) != payment.amount):
        raise ValueError("eSewa status does not match the initiated payment")
    return data


def response_signature_valid(data, payment):
    if not isinstance(data, dict):
        return False
    if data.get("signed_field_names") != SIGNED_RESPONSE_FIELDS:
        return False
    if (data.get("transaction_uuid") != payment.transaction_uuid
            or data.get("product_code") != settings.ESEWA_PRODUCT_CODE
            or money(data.get("total_amount")) != payment.amount
            or data.get("status") != "COMPLETE"):
        return False
    if any(field not in data or isinstance(data[field], (dict, list, type(None))) for field in SIGNED_RESPONSE_FIELDS.split(",")):
        return False
    signed_message = ",".join(f"{field}={data[field]}" for field in SIGNED_RESPONSE_FIELDS.split(","))
    return hmac.compare_digest(str(data.get("signature", "")), signature(signed_message))


@require_GET
def payment_summary(request):
    """Owner-only grouped expense totals. Only eSewa is provider-verified."""
    if not request.user.is_authenticated:
        return JsonResponse({"error": "Sign in required."}, status=401)
    paid = EsewaPayment.objects.filter(user=request.user, status="COMPLETE", expense__isnull=False)
    summary = paid.aggregate(amount=Sum("amount"))
    # Card/bank transactions are manually entered records, not provider confirmations.
    expenses = ExpenseTransaction.objects.filter(user=request.user, kind="expense")
    online_methods = ("eSewa (Sandbox)", "Card", "Bank Transfer")
    online = expenses.filter(payment_method__in=online_methods)
    offline = expenses.exclude(payment_method__in=online_methods)
    online_totals = online.aggregate(amount=Sum("amount"))
    offline_totals = offline.aggregate(amount=Sum("amount"))
    overall_totals = expenses.aggregate(amount=Sum("amount"))
    return JsonResponse({
        "paid_total": float(summary["amount"] or Decimal("0")),
        "successful_count": paid.count(),
        "online_total": float(online_totals["amount"] or Decimal("0")),
        "online_count": online.count(),
        "offline_total": float(offline_totals["amount"] or Decimal("0")),
        "offline_count": offline.count(),
        "total_expense_amount": float(overall_totals["amount"] or Decimal("0")),
        "total_expense_count": expenses.count(),
        "online_methods": ["eSewa", "Card", "Bank Transfer"],
        "offline_methods": ["Cash", "Other"],
        "is_test_environment": True,
    })


@require_POST
def start_checkout(request):
    if not request.user.is_authenticated:
        return JsonResponse({"error": "Sign in required."}, status=401)
    if not configured():
        return JsonResponse({"error": "eSewa sandbox is not configured. Enable test credentials first."}, status=503)
    if len(request.body) > 4096:
        return JsonResponse({"error": "Invalid payment request."}, status=400)
    try:
        data = json.loads(request.body)
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid payment request."}, status=400)
    if not isinstance(data, dict):
        return JsonResponse({"error": "Invalid payment details."}, status=400)
    amount = money(data.get("amount"))
    description = str(data.get("description", "")).strip()
    category = str(data.get("category", "")).strip()
    notes = str(data.get("notes", "")).strip()
    if len(notes) > 1000:
        return JsonResponse({"error": "Notes must be no longer than 1,000 characters."}, status=400)
    if not amount or not 1 <= len(description) <= 200 or not 1 <= len(category) <= 60:
        return JsonResponse({"error": "Enter a description, category and valid amount."}, status=400)

    month = timezone.localdate().replace(day=1)
    with transaction.atomic():
        budget = get_budget(request.user, month)
        budget = MonthlyBudget.objects.select_for_update().get(pk=budget.pk)
        if not budget.is_set_by_user:
            return JsonResponse({"error": "Set your monthly expense budget before paying."}, status=409)
        spent = monthly_spent(request.user, month)
        reserved = pending_reserved(request.user, month)
        if spent + reserved + amount > budget.limit:
            return JsonResponse({"error": "eSewa checkout blocked: monthly budget would be exceeded."}, status=409)
        category_budget = CategoryBudget.objects.select_for_update().filter(
            user=request.user, month=month, category__name__iexact=category).first()
        if category_budget:
            cat_spent = category_spending(request.user, category_budget.category, month)
            cat_reserved = pending_reserved(request.user, month, category=category)
            if cat_spent + cat_reserved + amount > category_budget.limit:
                return JsonResponse({"error": "eSewa checkout blocked: category budget would be exceeded."}, status=409)
        payment = EsewaPayment.objects.create(
            user=request.user, month=month, amount=amount, description=description,
            category=category, notes=notes, transaction_uuid="tn-" + uuid.uuid4().hex
        )
    return JsonResponse({"checkout_url": reverse("tn_esewa_checkout", args=[payment.transaction_uuid]),
                         "transaction_uuid": payment.transaction_uuid})


@require_GET
def pending_checkouts(request):
    """Only the signed-in user's active, reserving eSewa checkouts."""
    if not request.user.is_authenticated:
        return JsonResponse({"error": "Sign in required."}, status=401)
    cutoff = timezone.now() - timedelta(minutes=15)
    qs = EsewaPayment.objects.filter(
        user=request.user, status="PENDING", created_at__gte=cutoff
    ).order_by("-created_at")[:30]
    payments = [{
        "reference": p.transaction_uuid, "amount": float(p.amount),
        "category": p.category, "description": p.description,
        "created_at": p.created_at.isoformat(),
        "expires_at": (p.created_at + timedelta(minutes=15)).isoformat(),
        "checkout_url": reverse("tn_esewa_checkout", args=[p.transaction_uuid]),
    } for p in qs]
    return JsonResponse({"payments": payments})


@require_POST
def cancel_pending_checkout(request, reference):
    """Release reservation only after provider confirms payment is not complete.

    PENDING, unknown status, or verification errors are NOT safe to cancel.
    A provider-confirmed COMPLETE payment is finalized, never discarded.
    """
    if not request.user.is_authenticated:
        return JsonResponse({"error": "Sign in required."}, status=401)
    if not configured():
        return JsonResponse({"error": "eSewa verification is unavailable."}, status=503)
    with transaction.atomic():
        payment = EsewaPayment.objects.select_for_update().filter(
            user=request.user, transaction_uuid=reference
        ).first()
        if payment is None:
            return JsonResponse({"error": "Payment not found."}, status=404)
        if payment.status != "PENDING":
            return JsonResponse({"error": "This payment is no longer pending."}, status=409)
        try:
            result = status_from_esewa(payment)
        except (ValueError, URLError, HTTPError, TimeoutError, json.JSONDecodeError, OSError):
            logger.warning("Cannot safely release pending checkout %s: verification failed", payment.pk)
            return JsonResponse({
                "error": "Could not verify this payment with eSewa. Reservation remains protected; retry or allow the 15-minute reservation to expire."
            }, status=503)
        provider_status = str(result.get("status", "")).upper()
        if provider_status == "COMPLETE":
            # Finalization must happen even if the user pressed Cancel.
            finalized = finalize(payment, result)
            return JsonResponse({
                "error": "eSewa already confirmed payment. It has been recorded, not cancelled." if finalized
                else "Payment confirmed but recording needs investigation.",
                "complete": finalized
            }, status=409)
        if provider_status not in {"NOT_FOUND", "CANCELED", "CANCELLED", "FAILED", "EXPIRED"}:
            return JsonResponse({
                "error": f"eSewa reports {provider_status or 'UNKNOWN'}. The payment may still complete, so its reservation cannot safely be cancelled. You can resume it or let the 15-minute reservation expire."
            }, status=409)
        payment.status = "CANCELLED"
        payment.save(update_fields=["status"])
    return JsonResponse({
        "ok": True, "message": "Provider confirmed no completed payment. The pending reservation was released; no expense was recorded."
    })


@require_GET
def checkout_form(request, reference):
    if not request.user.is_authenticated:
        return redirect("/?login=1")
    payment = EsewaPayment.objects.filter(transaction_uuid=reference, user=request.user).first()
    if not payment:
        return render(request, "esewa_result.html", {"message": "Payment not found.", "success": False}, status=404)
    if not configured() or payment.status != "PENDING":
        return render(request, "esewa_result.html", {"message": "This checkout is no longer available.", "success": False}, status=409)
    if payment.created_at < timezone.now()-timedelta(minutes=15):
        return render(request, "esewa_result.html", {"message": "Checkout expired. Start a new payment.", "success": False}, status=409)
    total = f"{payment.amount:.2f}"
    fields = {
        "amount": total, "tax_amount": "0", "total_amount": total,
        "transaction_uuid": payment.transaction_uuid,
        "product_code": settings.ESEWA_PRODUCT_CODE,
        "product_service_charge": "0", "product_delivery_charge": "0",
        "success_url": request.build_absolute_uri(reverse("tn_esewa_success")),
        "failure_url": request.build_absolute_uri(reverse("tn_esewa_failure")),
        "signed_field_names": "total_amount,transaction_uuid,product_code",
    }
    fields["signature"] = signature(f"total_amount={total},transaction_uuid={payment.transaction_uuid},product_code={settings.ESEWA_PRODUCT_CODE}")
    return render(request, "esewa_checkout.html", {"action": FORM_URL, "fields": fields, "payment": payment})


def finalize(payment, provider_result):
    """Idempotently account for a verified payment, even if budgets changed after checkout."""
    if not normalize_result(provider_result):
        return False
    with transaction.atomic():
        item = EsewaPayment.objects.select_for_update().get(pk=payment.pk)
        if item.status == "COMPLETE":
            return True
        if item.status != "PENDING":
            return False
        if item.expense_id:
            # Existing record should never be duplicated.
            item.status = "COMPLETE"
            item.save(update_fields=["status"])
            return True
        # The payment must be recorded even when verification arrives late:
        # eSewa may already have completed an external transaction.
        # Use the verification date as the expense date if month rolled over.
        recorded_date = timezone.localdate()
        record_month = recorded_date.replace(day=1)
        expense = ExpenseTransaction.objects.create(
            user=item.user, date=recorded_date, kind="expense",
            description=item.description, category=item.category,
            amount=item.amount, payment_method="eSewa (Sandbox)",
            notes=(item.notes + "\n" if item.notes else "") +
                  "Verified sandbox eSewa test payment. No actual funds transferred.",
        )
        item.expense = expense
        item.status = "COMPLETE"
        item.reference_code = str(provider_result.get("ref_id", ""))[:80]
        item.verified_at = timezone.now()
        item.save(update_fields=["expense", "status", "reference_code", "verified_at"])
        current_budget = get_budget(item.user, record_month)
        current_budget = MonthlyBudget.objects.select_for_update().get(pk=current_budget.pk)
        current_spent = monthly_spent(item.user, record_month)
        evaluate_budget_alerts(item.user, record_month, triggering_expense=expense)
        if (current_spent - item.amount) * 100 >= current_budget.limit * 91:
            send_critical_expense_reminder(
                item.user, record_month, current_budget.limit, current_spent, expense.pk
            )
        if current_spent >= current_budget.limit:
            queue_budget_email(
                item.user, current_budget, record_month, triggering_expense=expense
            )
    return True


def verify_payment(request, payment, callback_data=None):
    if not configured():
        return False, "Sandbox verification is not configured."
    # If callback data is supplied it must be signed; never trust an unsigned
    # redirect as proof. We ALSO check the provider's status endpoint.
    if callback_data is not None and not response_signature_valid(callback_data, payment):
        return False, "Invalid or mismatched eSewa callback signature."
    try:
        provider_status = status_from_esewa(payment)
    except (ValueError, URLError, HTTPError, TimeoutError, json.JSONDecodeError, OSError):
        logger.exception("eSewa sandbox verification unavailable for payment %s", payment.pk)
        return False, "The payment could not be verified. It remains pending; retry the status check."
    if provider_status.get("status") != "COMPLETE":
        return False, "eSewa reports payment status: " + str(provider_status.get("status", "UNKNOWN")) + ". No expense recorded."
    if not finalize(payment, provider_status):
        return False, "The payment could not be finalized."
    return True, "eSewa SANDBOX payment verified. A test expense was recorded once."


@require_GET
def success(request):
    if not request.user.is_authenticated:
        return redirect("/?login=1")
    raw = request.GET.get("data", "")
    if not raw or len(raw) > 4096:
        return render(request, "esewa_result.html", {"success": False, "message": "Missing eSewa payment response."}, status=400)
    try:
        data = json.loads(base64.b64decode(raw, validate=True))
        if not isinstance(data, dict):
            raise ValueError()
    except (ValueError, TypeError, UnicodeDecodeError, json.JSONDecodeError, binascii.Error):
        return render(request, "esewa_result.html", {"success": False, "message": "Invalid eSewa payment response."}, status=400)
    payment = EsewaPayment.objects.filter(
        transaction_uuid=data.get("transaction_uuid"), user=request.user).first()
    if not payment:
        return render(request, "esewa_result.html", {"success": False, "message": "Unknown transaction."}, status=404)
    success_flag, message = verify_payment(request, payment, data)
    return render(request, "esewa_result.html", {"success": success_flag, "message": message,
                                                 "reference": payment.transaction_uuid})


@require_GET
def failure(request):
    return render(request, "esewa_result.html", {
        "success": False,
        "message": "eSewa did not confirm a payment. No expense was recorded. "
                   "If money was deducted, use status verification before trying again."
    })


@require_POST
def check_status(request, reference):
    if not request.user.is_authenticated:
        return JsonResponse({"error": "Sign in required."}, status=401)
    payment = EsewaPayment.objects.filter(user=request.user, transaction_uuid=reference).first()
    if not payment:
        return JsonResponse({"error": "Payment not found."}, status=404)
    success_flag, message = verify_payment(request, payment)
    return JsonResponse({"complete": success_flag, "message": message,
                         "status": "COMPLETE" if success_flag else "PENDING"})
