from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("kyc", "0001_initial"),
    ]

    operations = [
        migrations.RenameField(
            model_name="kycrecord",
            old_name="sumsub_applicant_id",
            new_name="provider_session_id",
        ),
        migrations.RenameField(
            model_name="kycrecord",
            old_name="sumsub_status",
            new_name="provider_status",
        ),
    ]
