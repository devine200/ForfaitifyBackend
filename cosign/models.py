from django.conf import settings
from django.db import models

from common.models import UUIDModel


class AgreementTemplate(UUIDModel):
    name = models.CharField(max_length=255)
    body = models.TextField(blank=True)
    docusign_template_id = models.CharField(max_length=128, blank=True)
    version = models.PositiveIntegerField(default=1)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="agreement_templates",
    )


class CosignInvite(UUIDModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        ACCEPTED = "accepted", "Accepted"
        EXPIRED = "expired", "Expired"

    token = models.CharField(max_length=64, unique=True, db_index=True)
    invoice = models.ForeignKey("invoices.Invoice", on_delete=models.CASCADE, related_name="cosign_invites")
    inviter = models.ForeignKey(
        "accounts.MerchantProfile",
        on_delete=models.CASCADE,
        related_name="sent_cosign_invites",
    )
    invitee_email = models.EmailField(blank=True)
    invitee_name = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    expires_at = models.DateTimeField(null=True, blank=True)


class CoSigner(UUIDModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SIGNED = "signed", "Signed"
        REJECTED = "rejected", "Rejected"

    invoice = models.ForeignKey("invoices.Invoice", on_delete=models.CASCADE, related_name="cosigners")
    invite = models.ForeignKey(
        CosignInvite,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="cosigners",
    )
    party_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="cosign_parties",
    )
    party_name = models.CharField(max_length=255)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    docusign_envelope_id = models.CharField(max_length=128, blank=True, db_index=True)
    signed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["created_at"]
