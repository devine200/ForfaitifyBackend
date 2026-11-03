from django.conf import settings
from django.db import models

from common.models import UUIDModel


class Balance(UUIDModel):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="balance",
    )
    currency = models.CharField(max_length=3, default="NGN")
    available_cents = models.BigIntegerField(default=0)
    held_cents = models.BigIntegerField(default=0)

    class Meta:
        verbose_name_plural = "balances"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(available_cents__gte=0),
                name="balance_available_cents_gte_0",
            ),
            models.CheckConstraint(
                condition=models.Q(held_cents__gte=0),
                name="balance_held_cents_gte_0",
            ),
        ]

    def __str__(self):
        return f"Balance<{self.user_id}> {self.available_cents} {self.currency}"


class BalanceTransaction(UUIDModel):
    class Type(models.TextChoices):
        DEPOSIT = "deposit", "Deposit"
        WITHDRAWAL = "withdrawal", "Withdrawal"
        REPAYMENT = "repayment", "Repayment"
        RETURN = "return", "Return"
        FEE = "fee", "Fee"
        FUNDING = "funding", "Funding"
        POOL_ALLOCATE = "pool_allocate", "Pool allocate"
        POOL_WITHDRAW = "pool_withdraw", "Pool withdraw"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PROCESSING = "processing", "Processing"
        SUCCESSFUL = "successful", "Successful"
        REJECTED = "rejected", "Rejected"

    balance = models.ForeignKey(Balance, on_delete=models.CASCADE, related_name="transactions")
    type = models.CharField(max_length=32, choices=Type.choices)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    amount_cents = models.BigIntegerField()
    destination_label = models.CharField(max_length=255, blank=True)
    invoice = models.ForeignKey(
        "invoices.Invoice",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="balance_transactions",
    )
    pool = models.ForeignKey(
        "pools.Pool",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="balance_transactions",
    )
    payment_intent = models.ForeignKey(
        "payments.PaymentIntent",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="balance_transactions",
    )
    idempotency_key = models.CharField(max_length=128, unique=True, null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
