from django.conf import settings
from django.db import models

from common.models import UUIDModel


class Pool(UUIDModel):
    class Type(models.TextChoices):
        CENTRALIZED = "centralized", "Centralized"
        CUSTOM = "custom", "Custom"

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        INACTIVE = "inactive", "Inactive"

    name = models.CharField(max_length=255)
    type = models.CharField(max_length=16, choices=Type.choices)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    closed = models.BooleanField(default=False)
    owner_investor = models.ForeignKey(
        "accounts.InvestorProfile",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="owned_pools",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_pools",
    )
    countries = models.JSONField(default=list, blank=True)
    industries = models.JSONField(default=list, blank=True)
    strategy = models.TextField(blank=True)
    min_deposit_cents = models.BigIntegerField(default=10000)
    target_size_cents = models.BigIntegerField(null=True, blank=True)
    exposure_limit_percent = models.DecimalField(max_digits=5, decimal_places=2, default=15)
    auto_funding = models.BooleanField(default=True)
    allow_public = models.BooleanField(default=False)
    target_return_bps = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} ({self.type})"


class PoolLoanTier(UUIDModel):
    pool = models.ForeignKey(Pool, on_delete=models.CASCADE, related_name="loan_tiers")
    name = models.CharField(max_length=64)
    duration_days = models.PositiveIntegerField()
    interest_bps = models.PositiveIntegerField()
    invoice_min_cents = models.BigIntegerField()
    invoice_max_cents = models.BigIntegerField()

    class Meta:
        ordering = ["interest_bps"]


class PoolPosition(UUIDModel):
    pool = models.ForeignKey(Pool, on_delete=models.CASCADE, related_name="positions")
    investor = models.ForeignKey(
        "accounts.InvestorProfile",
        on_delete=models.CASCADE,
        related_name="positions",
    )
    principal_cents = models.BigIntegerField(default=0)

    class Meta:
        unique_together = ("pool", "investor")


class PoolWithdrawalRequest(UUIDModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        ACCEPTED = "accepted", "Accepted"
        REJECTED = "rejected", "Rejected"
        SETTLED = "settled", "Settled"

    pool = models.ForeignKey(Pool, on_delete=models.CASCADE, related_name="withdrawal_requests")
    investor = models.ForeignKey(
        "accounts.InvestorProfile",
        on_delete=models.CASCADE,
        related_name="pool_withdrawals",
    )
    amount_cents = models.BigIntegerField()
    pool_share_bps_snapshot = models.PositiveIntegerField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    requested_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-requested_at"]
