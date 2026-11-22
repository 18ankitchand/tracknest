from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("accounts", "0003_esewa_checkout")]
    operations = [
        migrations.AddField(
            model_name="esewapayment",
            name="notes",
            field=models.TextField(blank=True, default=""),
        ),
    ]
