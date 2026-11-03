from django.conf import settings
from django.db import models

from common.models import UUIDModel


class PayoutMethod(UUIDModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="payout_methods",
    )
    label = models.CharField(max_length=128)
    account_ref = models.CharField(max_length=255)
    bank_code = models.CharField(max_length=32, blank=True)
    account_name = models.CharField(max_length=255, blank=True)
    is_default = models.BooleanField(default=False)

    class Meta:
        ordering = ["-is_default", "-created_at"]


class PaymentIntent(UUIDModel):
    class Kind(models.TextChoices):
        DEPOSIT = "deposit", "Deposit"
        WITHDRAWAL = "withdrawal", "Withdrawal"
        INVOICE_PAYOUT = "invoice_payout", "Invoice payout"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PROCESSING = "processing", "Processing"
        SUCCESSFUL = "successful", "Successful"
        REJECTED = "rejected", "Rejected"
        EXPIRED = "expired", "Expired"

    class AdminDecision(models.TextChoices):
        APPROVE = "approve", "Approve"
        REJECT = "reject", "Reject"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="payment_intents",
    )
    kind = models.CharField(max_length=16, choices=Kind.choices)
    amount_cents = models.BigIntegerField()
    currency = models.CharField(max_length=3, default="NGN")
    invoice = models.ForeignKey(
        "invoices.Invoice",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payment_intents",
    )
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    processor = models.CharField(max_length=64, default="dummy")
    processor_ref = models.CharField(max_length=255, blank=True, db_index=True)
    payout_method = models.ForeignKey(
        PayoutMethod,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="intents",
    )
    requires_admin_review = models.BooleanField(default=False)
    admin_decision = models.CharField(
        max_length=16,
        choices=AdminDecision.choices,
        blank=True,
    )
    idempotency_key = models.CharField(max_length=128, unique=True, null=True, blank=True)
    settled_at = models.DateTimeField(null=True, blank=True)
    meta = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
