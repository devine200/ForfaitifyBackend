from django.db import models

from common.models import UUIDModel


class Invoice(UUIDModel):
    class ReviewStatus(models.TextChoices):
        PENDING_REVIEW = "pending_review", "Pending review"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    class InsuranceStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        VERIFIED = "verified", "Verified"
        REJECTED = "rejected", "Rejected"

    class FinanceStep(models.TextChoices):
        CREATED = "created", "Created"
        FUNDING = "funding", "Funding"
        FINANCE_FUNDED = "finance_funded", "Finance Funded"
        FUNDING_WITHDRAWN = "funding_withdrawn", "Funding Withdrawn"
        FINANCE_MATURED = "finance_matured", "Finance Matured"
        FINANCE_REPAID = "finance_repaid", "Finance Repaid"

    class PayoutStatus(models.TextChoices):
        NONE = "none", "None"
        READY = "ready", "Ready"
        PENDING = "pending", "Pending"
        SETTLED = "settled", "Settled"

    class RepaymentState(models.TextChoices):
        NOT_STARTED = "not_started", "Not started"
        CURRENT = "current", "Current"
        OVERDUE = "overdue", "Overdue"
        REPAID = "repaid", "Repaid"

    class DisplayStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        PROCESSING = "processing", "Processing"
        SUCCESSFUL = "successful", "Successful"
        REJECTED = "rejected", "Rejected"

    code = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=255)
    title = models.CharField(max_length=255, blank=True)
    merchant = models.ForeignKey(
        "accounts.MerchantProfile",
        on_delete=models.CASCADE,
        related_name="invoices",
    )
    buyer_name = models.CharField(max_length=255, blank=True)
    industry = models.CharField(max_length=128, blank=True)
    country = models.CharField(max_length=128, blank=True)
    years_in_operation_snapshot = models.PositiveIntegerField(default=0)
    total_amount_cents = models.BigIntegerField(default=0)
    loan_amount_cents = models.BigIntegerField(default=0)
    duration_days = models.PositiveIntegerField(default=30)
    due_date = models.DateField(null=True, blank=True)
    apr_bps = models.PositiveIntegerField(default=0)
    risk_tier = models.ForeignKey(
        "pools.PoolLoanTier",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="invoices",
    )
    pool = models.ForeignKey(
        "pools.Pool",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="invoices",
    )
    review_status = models.CharField(
        max_length=32,
        choices=ReviewStatus.choices,
        default=ReviewStatus.PENDING_REVIEW,
    )
    insurance_status = models.CharField(
        max_length=16,
        choices=InsuranceStatus.choices,
        default=InsuranceStatus.PENDING,
    )
    finance_step = models.CharField(
        max_length=32,
        choices=FinanceStep.choices,
        default=FinanceStep.CREATED,
    )
    payout_status = models.CharField(
        max_length=16,
        choices=PayoutStatus.choices,
        default=PayoutStatus.NONE,
    )
    repayment_state = models.CharField(
        max_length=16,
        choices=RepaymentState.choices,
        default=RepaymentState.NOT_STARTED,
    )
    display_status = models.CharField(
        max_length=16,
        choices=DisplayStatus.choices,
        default=DisplayStatus.PENDING,
    )
    repayment_amount_cents = models.BigIntegerField(default=0)
    outstanding_cents = models.BigIntegerField(default=0)
    funded_amount_cents = models.BigIntegerField(default=0)
    amount_left_cents = models.BigIntegerField(default=0)
    funding_closes_at = models.DateTimeField(null=True, blank=True)
    funded_at = models.DateTimeField(null=True, blank=True)
    inactive = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.code} · {self.name}"


class InvoiceDocument(UUIDModel):
    class Visibility(models.TextChoices):
        AVAILABLE = "available", "Available"
        REDACTED = "redacted", "Redacted"

    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="documents")
    name = models.CharField(max_length=255)
    file = models.FileField(upload_to="invoices/%Y/%m/", blank=True)
    visibility = models.CharField(
        max_length=16,
        choices=Visibility.choices,
        default=Visibility.AVAILABLE,
    )


class InvoiceAcknowledgement(UUIDModel):
    class Kind(models.TextChoices):
        REPAYMENT_TERMS = "repayment_terms", "Repayment terms"
        LATE_PENALTIES = "late_penalties", "Late penalties"
        CONTRACT_ENFORCEMENT = "contract_enforcement", "Contract enforcement"

    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="acknowledgements")
    kind = models.CharField(max_length=32, choices=Kind.choices)
    acked_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("invoice", "kind")
