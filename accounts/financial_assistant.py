"""TrackNest financial assistant.

This is a local, data-grounded financial assistant, not a generative LLM.
It never edits financial records. Users manage data in the linked workspaces.
"""
import json
import re
from datetime import timedelta
from decimal import Decimal

from django.db.models import Sum
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import CategoryBudget, ExpenseTransaction, MonthlyBudget, SavingsGoal


ZERO = Decimal("0.00")


def amount_text(amount):
    return f"Nrs {amount:,.2f}"


def total(queryset):
    return queryset.aggregate(value=Sum("amount"))["value"] or ZERO


def assistant_data(user):
    today = timezone.localdate()
    start = today.replace(day=1)
    transactions = ExpenseTransaction.objects.filter(user=user)
    this_month = transactions.filter(date__year=today.year, date__month=today.month)
    income = total(this_month.filter(kind="income"))
    expense = total(this_month.filter(kind="expense"))
    all_income = total(transactions.filter(kind="income"))
    all_expense = total(transactions.filter(kind="expense"))
    budget = MonthlyBudget.objects.filter(user=user, month=start).first()
    limit = budget.limit if budget else Decimal("50000.00")
    spent_by_category = {
        row["category"]: row["total"]
        for row in this_month.filter(kind="expense")
        .values("category").annotate(total=Sum("amount"))
    }
    category_budgets = list(
        CategoryBudget.objects.filter(user=user, month=start)
        .select_related("category").order_by("category__name")
    )
    goals = list(SavingsGoal.objects.filter(user=user).order_by("name"))
    return {
        "today": today, "month": start, "all_tx": transactions,
        "recent": list(transactions.order_by("-date", "-id")[:5]),
        "income": income, "expense": expense,
        "balance": all_income - all_expense,
        "net_savings": income - expense,
        "limit": limit, "remaining": limit - expense,
        "category_spending": spent_by_category,
        "category_budgets": category_budgets,
        "goals": goals,
    }


def classify(question):
    q = question.casefold()
    def contains(*terms):
        return any(term in q for term in terms)
    if contains("help", "what can you", "how do i", "how to", "what do you"):
        return "help"
    if contains("recent", "last transaction", "latest", "transaction history", "list transaction"):
        return "transactions"
    if contains("savings goal", "saving goal", "goal progress", "my goals", "target"):
        return "goals"
    if contains("category", "categories", "where am i spending", "where do i spend", "biggest expense", "top expense", "most spent"):
        return "categories"
    if contains("budget", "limit", "remaining", "overspend", "can i spend", "afford"):
        return "budget"
    if contains("how to save", "save more", "saving tips", "reduce spending", "cut expenses", "suggest", "advice", "recommend"):
        return "advice"
    if contains("income", "salary", "earning", "earned", "received"):
        return "income"
    if contains("expense", "spending", "spent", "cost", "outflow"):
        return "expenses"
    if contains("saving", "savings", "net", "balance", "overview", "summary", "financial"):
        return "overview"
    return "overview"


def reply(user, question):
    d = assistant_data(user)
    mode = classify(question)
    navigation = {
        "help": "dashboard", "transactions": "transactions",
        "goals": "goals", "categories": "reports", "budget": "budget",
        "advice": "budget", "income": "income", "expenses": "expense",
        "overview": "dashboard",
    }
    destination = navigation[mode]
    intro = f"For {d['month']:%B %Y}, "
    if mode == "help":
        message = (
            "I can review your recorded income, expenses, balance, monthly "
            "and category budgets, recent transactions, and savings goals. "
            "Try asking 'How much did I spend this month?', "
            "'What is my remaining budget?', 'Where do I spend the most?', "
            "or 'How are my savings goals going?'. "
            "I can suggest next steps, but I cannot change records from chat."
        )
    elif mode == "transactions":
        if not d["recent"]:
            message = "You have no recorded transactions yet. Add income or expenses to get started."
        else:
            parts = [
                f"{tx.date:%d %b}: {tx.description} — "
                f"{'+' if tx.kind == 'income' else '-'}{amount_text(tx.amount)} "
                f"({tx.category})"
                for tx in d["recent"]
            ]
            message = "Your five most recent recorded transactions:\n" + "\n".join(parts)
    elif mode == "income":
        message = (
            intro + f"you recorded income of {amount_text(d['income'])}. "
            "Open Income to add, review, or correct a record."
        )
    elif mode == "expenses":
        message = (
            intro + f"you recorded expenses of {amount_text(d['expense'])}. "
            f"Your remaining monthly recording budget is {amount_text(max(ZERO, d['remaining']))}. "
            "Open Expenses to review or edit the transactions."
        )
    elif mode == "budget":
        percentage = d["expense"] / d["limit"] * 100 if d["limit"] else ZERO
        status = (
            "limit reached; further expenses cannot be recorded in TrackNest"
            if percentage >= 100 else
            "critical warning" if percentage >= 90 else
            "warning" if percentage >= 80 else "within budget"
        )
        message = (
            intro + f"your overall budget is {amount_text(d['limit'])}, "
            f"with {amount_text(d['expense'])} spent ({percentage:.1f}%). "
            f"Remaining: {amount_text(max(ZERO, d['remaining']))}. Status: {status}. "
        )
        if d["category_budgets"]:
            entries = []
            for budget in d["category_budgets"][:6]:
                spent = d["category_spending"].get(budget.category.name, ZERO)
                entries.append(
                    f"{budget.category.name}: {amount_text(spent)} / {amount_text(budget.limit)}"
                )
            message += "Category budgets: " + "; ".join(entries) + ". "
        message += "The limit only controls expense recording inside TrackNest, not external payments."
    elif mode == "categories":
        categories = sorted(d["category_spending"].items(), key=lambda item: item[1], reverse=True)
        if not categories:
            message = "No expenses are recorded for this month. Once you add expenses, I can show which categories cost the most."
        else:
            top = categories[:5]
            message = (
                f"Your highest spending categories for {d['month']:%B %Y}: "
                + "; ".join(f"{name}: {amount_text(spent)}" for name, spent in top)
                + ". Review these categories in Reports before deciding where to cut back."
            )
    elif mode == "goals":
        if not d["goals"]:
            message = (
                "You haven't created a savings goal yet. Open Savings Goals "
                "to set a target and record savings allocations."
            )
        else:
            results = []
            for goal in d["goals"][:6]:
                saved = goal.contributions.aggregate(value=Sum("amount"))["value"] or ZERO
                progress = (saved / goal.target * 100) if goal.target else ZERO
                results.append(
                    f"{goal.name}: {amount_text(saved)} / {amount_text(goal.target)} "
                    f"({progress:.0f}% complete)"
                )
            message = "Your recorded savings goals:\n" + "\n".join(results)
            message += "\nGoal contributions are allocations, not automatic bank transfers."
    elif mode == "advice":
        categories = sorted(d["category_spending"].items(), key=lambda item: item[1], reverse=True)
        suggestions = [
            f"This month you earned {amount_text(d['income'])} and spent {amount_text(d['expense'])}.",
            f"Your recorded net savings are {amount_text(d['net_savings'])}.",
        ]
        if d["net_savings"] < ZERO:
            suggestions.append("Expenses exceed income this month. Review discretionary purchases and upcoming bills.")
        elif d["income"] > ZERO:
            suggestions.append(
                "If this income is stable, consider setting aside a manageable portion for a savings goal."
            )
        if categories:
            category, value = categories[0]
            suggestions.append(
                f"Your largest expense category is {category} ({amount_text(value)}). Review individual purchases before reducing its budget."
            )
        pct = d["expense"] / d["limit"] * 100 if d["limit"] else ZERO
        if pct >= 80:
            suggestions.append(
                f"You have used {pct:.0f}% of your monthly budget. Check upcoming essential expenses before adding new ones."
            )
        message = " ".join(suggestions)
    else:
        message = (
            intro + f"your income is {amount_text(d['income'])}, "
            f"expenses are {amount_text(d['expense'])}, and net monthly savings "
            f"are {amount_text(d['net_savings'])}. "
            f"Your all-time recorded balance is {amount_text(d['balance'])}. "
            "Ask about categories, budgets, goals, or recent transactions for more detail."
        )
    return {"reply": message, "section": destination, "mode": "local_financial_insights"}


@require_POST
def financial_assistant(request):
    if not request.user.is_authenticated:
        return JsonResponse({"error": "Sign in to use your financial assistant."}, status=401)
    if len(request.body) > 4096:
        return JsonResponse({"error": "Message is too long."}, status=400)
    try:
        data = json.loads(request.body)
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid message."}, status=400)
    if not isinstance(data, dict) or not isinstance(data.get("message"), str):
        return JsonResponse({"error": "Enter a question."}, status=400)
    message = data["message"].strip()
    if not message or len(message) > 500:
        return JsonResponse({"error": "Enter a question up to 500 characters."}, status=400)
    return JsonResponse(reply(request.user, message))
