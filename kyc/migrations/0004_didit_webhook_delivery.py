from django.db import migrations, models
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ("kyc", "0003_verification_kind"),
    ]

    operations = [
        migrations.CreateModel(
            name="DiditWebhookDelivery",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("event_id", models.CharField(max_length=64, unique=True)),
            ],
            options={"ordering": ["-created_at"]},
        ),
    ]
