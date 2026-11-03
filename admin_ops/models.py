from django.conf import settings
from django.db import models

from common.models import UUIDModel


class PlatformFees(UUIDModel):
    platform_fee_bps = models.PositiveIntegerField(default=250)
    withdrawal_fee_bps = models.PositiveIntegerField(default=350)
    lateness_fee_bps = models.PositiveIntegerField(default=1050)
    effective_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-effective_at"]
        verbose_name_plural = "platform fees"


class PaymentGatewayConfig(UUIDModel):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        INACTIVE = "inactive", "Inactive"

    name = models.CharField(max_length=128)
    detail = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.INACTIVE)
    is_primary = models.BooleanField(default=False)

    class Meta:
        ordering = ["-is_primary", "name"]


class AdminInvite(UUIDModel):
    class Status(models.TextChoices):
        INVITED = "invited", "Invited"
        ACCEPTED = "accepted", "Accepted"
        DISABLED = "disabled", "Disabled"

    email = models.EmailField()
    full_name = models.CharField(max_length=255, blank=True)
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="admin_invites_sent",
    )
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.INVITED)
    token = models.CharField(max_length=64, unique=True)

    class Meta:
        ordering = ["-created_at"]
