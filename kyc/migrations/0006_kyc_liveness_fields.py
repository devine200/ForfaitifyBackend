from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("kyc", "0005_kyc_record_per_kind"),
    ]

    operations = [
        migrations.AddField(
            model_name="kycrecord",
            name="liveness_score",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="kycrecord",
            name="liveness_status",
            field=models.CharField(
                blank=True,
                choices=[
                    ("pending", "Pending"),
                    ("processing", "Processing"),
                    ("approved", "Approved"),
                    ("rejected", "Rejected"),
                ],
                default="",
                max_length=16,
            ),
        ),
    ]
