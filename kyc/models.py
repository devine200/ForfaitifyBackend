from django.conf import settings
from django.db import models

from common.models import UUIDModel


class ReviewStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    PROCESSING = "processing", "Processing"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"


class VerificationKind(models.TextChoices):
    KYC = "kyc", "KYC"
    KYB = "kyb", "KYB"


class DiditWebhookDelivery(UUIDModel):
    """One row per Didit event_id so retries are ignored."""

    event_id = models.CharField(max_length=64, unique=True)

    class Meta:
        ordering = ["-created_at"]


class KycRecord(UUIDModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="kyc_records",
    )
    verification_kind = models.CharField(
        max_length=8,
        choices=VerificationKind.choices,
        blank=True,
    )
    provider_session_id = models.CharField(max_length=128, blank=True, db_index=True)
    provider_status = models.CharField(
        max_length=16,
        choices=ReviewStatus.choices,
        default=ReviewStatus.PENDING,
    )
    admin_status = models.CharField(
        max_length=16,
        choices=ReviewStatus.choices,
        default=ReviewStatus.PENDING,
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="kyc_reviews",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    raw_webhook_payload = models.JSONField(null=True, blank=True)

    class Meta:
        ordering = ["-updated_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "verification_kind"],
                name="uniq_kyc_user_kind",
            )
        ]

    def __str__(self):
        return f"KYC<{self.user_id}> provider={self.provider_status} admin={self.admin_status}"

    @property
    def is_fully_approved(self) -> bool:
        return (
            self.provider_status == ReviewStatus.APPROVED
            and self.admin_status == ReviewStatus.APPROVED
        )
