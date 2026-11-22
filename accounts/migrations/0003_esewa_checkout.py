from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def mark_existing_budgets_configured(apps, schema_editor):
    # Preserve the established experience for existing accounts. New accounts
    # must explicitly set a budget; older users can keep their saved budgets.
    apps.get_model("accounts", "MonthlyBudget").objects.all().update(is_set_by_user=True)


class Migration(migrations.Migration):
    dependencies = [("accounts", "0002_premium_finance"), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.AddField(model_name="monthlybudget", name="is_set_by_user",
                            field=models.BooleanField(default=False)),
        migrations.RunPython(mark_existing_budgets_configured, migrations.RunPython.noop),
        migrations.CreateModel(
            name="EsewaPayment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("transaction_uuid", models.CharField(max_length=64, unique=True)),
                ("description", models.CharField(max_length=200)),
                ("category", models.CharField(max_length=60)),
                ("amount", models.DecimalField(max_digits=12, decimal_places=2)),
                ("month", models.DateField()),
                ("status", models.CharField(default="PENDING", max_length=16)),
                ("reference_code", models.CharField(blank=True, default="", max_length=80)),
                ("is_sandbox", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("verified_at", models.DateTimeField(blank=True, null=True)),
                ("expense", models.OneToOneField(blank=True, null=True,
                    on_delete=django.db.models.deletion.PROTECT, related_name="esewa_payment", to="accounts.expensetransaction")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                    related_name="esewa_payments", to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.AddIndex(model_name="esewapayment",
                            index=models.Index(fields=["user", "month", "status"], name="tn_esewa_user_month_status")),
    ]
