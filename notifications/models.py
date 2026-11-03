from django.conf import settings
from django.db import models

from common.models import UUIDModel


class Notification(UUIDModel):
    class RoleScope(models.TextChoices):
        MERCHANT = "merchant", "Merchant"
        INVESTOR = "investor", "Investor"
        ADMIN = "admin", "Admin"

    class Kind(models.TextChoices):
        ALERT = "alert", "Alert"
        WARN = "warn", "Warn"
        SEND = "send", "Send"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    role_scope = models.CharField(max_length=16, choices=RoleScope.choices)
    category = models.CharField(max_length=64)
    kind = models.CharField(max_length=16, choices=Kind.choices, default=Kind.SEND)
    title = models.CharField(max_length=255)
    body = models.TextField()
    urgent = models.BooleanField(default=False)
    href = models.CharField(max_length=512, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]


class EmailDelivery(UUIDModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"
        SKIPPED_PREF = "skipped_pref", "Skipped preference"
        SKIPPED_DEDUP = "skipped_dedup", "Skipped dedup"
        RATE_LIMITED = "rate_limited", "Rate limited"
        CIRCUIT_OPEN = "circuit_open", "Circuit open"

    idempotency_key = models.CharField(max_length=255, unique=True)
    to_email = models.EmailField()
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="email_deliveries",
    )
    event_type = models.CharField(max_length=128)
    category = models.CharField(max_length=64, blank=True)
    notification = models.ForeignKey(
        Notification,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="email_deliveries",
    )
    template_name = models.CharField(max_length=128, blank=True)
    status = models.CharField(
        max_length=32, choices=Status.choices, default=Status.PENDING
    )
    provider_message_id = models.CharField(max_length=255, blank=True)
    error = models.TextField(blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
