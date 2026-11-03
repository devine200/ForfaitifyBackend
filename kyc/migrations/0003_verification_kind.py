from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("kyc", "0002_rename_sumsub_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="kycrecord",
            name="verification_kind",
            field=models.CharField(
                blank=True,
                choices=[("kyc", "KYC"), ("kyb", "KYB")],
                max_length=8,
            ),
        ),
    ]
