from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("budget", "0001_initial")]

    operations = [
        migrations.AlterField(
            model_name="invoicedraft",
            name="status",
            field=models.CharField(
                choices=[
                    ("review", "Needs review"),
                    ("ready", "Ready"),
                    ("imported", "Imported"),
                    ("dismissed", "Dismissed"),
                ],
                default="review",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="invoicedraft",
            name="imported_fiscal_year",
            field=models.CharField(blank=True, max_length=9),
        ),
        migrations.AddField(
            model_name="invoicedraft",
            name="imported_transaction_id",
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name="invoicedraft",
            name="imported_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
