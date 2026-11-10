import secrets
from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from django.db.models import Sum

from admin_ops.fees import bps_of, current_fees
from balances.models import BalanceTransaction
from balances.services import (
    credit_available,
    debit_available,
    invoice_funding_remaining_cents,
    record_fee,
)
from invoices.models import Invoice
from notifications.emit import emit, invoice_room
from notifications.formatting import format_usd
from notifications.keys import key
from pools.models import Pool, PoolPosition


def _pool_available_liquidity_cents(pool) -> int:
    principal = (
        PoolPosition.objects.filter(pool=pool).aggregate(s=Sum("principal_cents"))["s"] or 0
    )
    deployed = (
        Invoice.objects.filter(pool=pool, funded_amount_cents__gt=0)
        .exclude(finance_step=Invoice.FinanceStep.FINANCE_REPAID)
        .aggregate(s=Sum("funded_amount_cents"))["s"]
        or 0
    )
    return max(0, principal - deployed)


def generate_invoice_code() -> str:
    return f"IN-{secrets.token_hex(4).upper()}"


def _merchant_invoice_keys(invoice: Invoice) -> list:
    return [
        key("merchantInvoices"),
        key("merchantInvoice", str(invoice.id)),
        key("merchantDashboard"),
        key("adminInvoices"),
        key("adminInvoice", str(invoice.id)),
        key("adminDashboard"),
        key("notifications"),
    ]


@transaction.atomic
def review_invoice(invoice: Invoice, decision: str) -> Invoice:
    if invoice.review_status != Invoice.ReviewStatus.PENDING_REVIEW:
        raise ValidationError("Invoice is not pending review.")
    if decision == "approve":
        invoice.review_status = Invoice.ReviewStatus.APPROVED
        invoice.display_status = Invoice.DisplayStatus.PROCESSING
        invoice.finance_step = Invoice.FinanceStep.FUNDING
        invoice.inactive = False
    elif decision == "reject":
        invoice.review_status = Invoice.ReviewStatus.REJECTED
        invoice.display_status = Invoice.DisplayStatus.REJECTED
        invoice.inactive = True
    else:
        raise ValidationError("decision must be approve or reject.")
    invoice.save()
    approved = decision == "approve"
    emit(
        event_type="invoice.reviewed",
        user=invoice.merchant.user,
        notify_admins=True,
        role_scope="merchant",
        notification={
            "category": "invoiceUpdates",
            "kind": "send" if approved else "alert",
            "title": f"Invoice {invoice.code} was {'approved' if approved else 'rejected'}",
            "body": (
                "Your receivable is moving into funding."
                if approved
                else "Review the rejection and update your submission if needed."
            ),
            "urgent": not approved,
            "href": f"/merchant/invoices/{invoice.id}",
        },
        invalidate=_merchant_invoice_keys(invoice),
        room=invoice_room(invoice.id),
        email=False,
    )
    return invoice


@transaction.atomic
def set_insurance(invoice: Invoice, status: str) -> Invoice:
    if status not in Invoice.InsuranceStatus.values:
        raise ValidationError("Invalid insurance status.")
    invoice.insurance_status = status
    invoice.save(update_fields=["insurance_status", "updated_at"])
    return invoice


@transaction.atomic
def fund_invoice(invoice: Invoice, pool) -> Invoice:
    if invoice.review_status != Invoice.ReviewStatus.APPROVED:
        raise ValidationError("Invoice must be approved before funding.")
    if invoice.insurance_status != Invoice.InsuranceStatus.VERIFIED:
        raise ValidationError("Insurance must be verified before funding.")
    if invoice.funded_amount_cents > 0 and invoice.finance_step == Invoice.FinanceStep.FINANCE_FUNDED:
        raise ValidationError("Invoice is already funded.")
    pool = Pool.objects.select_for_update().get(pk=pool.pk)
    amount = invoice.loan_amount_cents
    if amount <= 0:
        raise ValidationError("Invoice has no loan amount to fund.")
    liquidity = _pool_available_liquidity_cents(pool)
    if liquidity < amount:
        raise ValidationError(
            f"Pool does not have enough liquidity ({liquidity} available, {amount} required)."
        )
    invoice.pool = pool
    invoice.funded_amount_cents = amount
    invoice.amount_left_cents = 0
    invoice.outstanding_cents = invoice.repayment_amount_cents or amount
    invoice.finance_step = Invoice.FinanceStep.FINANCE_FUNDED
    invoice.payout_status = Invoice.PayoutStatus.READY
    invoice.display_status = Invoice.DisplayStatus.SUCCESSFUL
    invoice.funded_at = timezone.now()
    invoice.save()

    # Credit merchant balance tagged to this invoice + pool (segregated funding).
    credit_available(
        invoice.merchant.user,
        invoice.funded_amount_cents,
        tx_type=BalanceTransaction.Type.FUNDING,
        destination_label=f"Invoice funding {invoice.code}",
        invoice=invoice,
        pool=pool,
        idempotency_key=f"fund-{invoice.id}",
    )
    investor_users = [
        p.investor.user
        for p in PoolPosition.objects.filter(pool=pool).select_related("investor__user")
    ]
    emit(
        event_type="invoice.funded",
        user=invoice.merchant.user,
        users=investor_users,
        notify_admins=True,
        role_scope="merchant",
        notification={
            "category": "invoiceUpdates",
            "kind": "send",
            "title": f"Invoice {invoice.code} was financed",
            "body": (
                f"Your receivable was matched to a pool and "
                f"{format_usd(invoice.funded_amount_cents)} is ready in your balance."
            ),
            "href": f"/merchant/invoices/{invoice.id}",
        },
        invalidate=_merchant_invoice_keys(invoice)
        + [
            key("balance"),
            key("balanceTx"),
            key("pools"),
            key("pool", str(pool.id)),
            key("investorDashboard"),
            key("investorInvoices"),
        ],
        room=invoice_room(invoice.id),
        email="money",
        idempotency_key=f"email:invoice.funded:{invoice.id}",
        email_context={
            "amount_cents": invoice.funded_amount_cents,
            "invoice_code": invoice.code,
            "pool_name": getattr(pool, "name", ""),
        },
    )
    for iu in investor_users:
        emit(
            event_type="invoice.funded.investor",
            user=iu,
            role_scope="investor",
            notification={
                "category": "poolMatching",
                "kind": "send",
                "title": f"Pool matched invoice {invoice.code}",
                "body": f"{format_usd(invoice.funded_amount_cents)} was deployed from your pool.",
                "href": f"/investor/pools/{pool.id}",
            },
            invalidate=[
                key("investorDashboard"),
                key("investorInvoices"),
                key("pools"),
                key("pool", str(pool.id)),
                key("notifications"),
            ],
            email="investment",
            idempotency_key=f"email:invoice.funded.investor:{invoice.id}:{iu.id}",
            email_context={
                "amount_cents": invoice.funded_amount_cents,
                "invoice_code": invoice.code,
                "pool_name": getattr(pool, "name", ""),
            },
        )
    return invoice


@transaction.atomic
def withdraw_funding(invoice: Invoice, payout_method) -> Invoice:
    """Hold funding and queue an invoice payout for admin approval → transfer."""
    from django.conf import settings

    from payments.models import PaymentIntent
    from utils import payments as payment_util

    invoice = Invoice.objects.select_for_update().get(pk=invoice.pk)
    if invoice.payout_status != Invoice.PayoutStatus.READY:
        raise ValidationError("Funding is not ready to withdraw.")
    if invoice.finance_step != Invoice.FinanceStep.FINANCE_FUNDED:
        raise ValidationError("Invoice is not in a withdrawable state.")
    remaining = invoice_funding_remaining_cents(invoice)
    if remaining <= 0:
        raise ValidationError("No remaining funded amount available to withdraw for this invoice.")
    payout_amount = remaining

    existing_pending = PaymentIntent.objects.filter(
        invoice=invoice,
        kind=PaymentIntent.Kind.INVOICE_PAYOUT,
        status__in=[PaymentIntent.Status.PENDING, PaymentIntent.Status.PROCESSING],
    ).first()
    if existing_pending:
        raise ValidationError("A payout for this invoice is already pending.")

    idem = f"inv-payout-{invoice.id}-{timezone.now().strftime('%Y%m%d%H%M%S')}"
    result = payment_util.create_withdrawal(
        str(invoice.merchant.user_id),
        payout_amount,
        payout_method.account_ref,
        currency=settings.DEFAULT_CURRENCY,
        idempotency_key=idem,
    )
    intent = PaymentIntent.objects.create(
        user=invoice.merchant.user,
        kind=PaymentIntent.Kind.INVOICE_PAYOUT,
        amount_cents=payout_amount,
        currency=settings.DEFAULT_CURRENCY,
        status=PaymentIntent.Status.PENDING,
        processor=result.processor,
        processor_ref=result.processor_ref,
        payout_method=payout_method,
        invoice=invoice,
        requires_admin_review=True,
        idempotency_key=idem,
        meta={**(result.raw or {}), "pool_id": str(invoice.pool_id) if invoice.pool_id else None},
    )
    debit_available(
        invoice.merchant.user,
        payout_amount,
        tx_type=BalanceTransaction.Type.WITHDRAWAL,
        destination_label=f"{payout_method.label} — {payout_method.account_ref[-4:]}",
        invoice=invoice,
        pool=invoice.pool,
        payment_intent=intent,
        idempotency_key=f"inv-withdraw-hold-{invoice.id}",
        hold=True,
    )
    invoice.payout_status = Invoice.PayoutStatus.PENDING
    if invoice.due_date is None:
        invoice.due_date = (timezone.now() + timedelta(days=invoice.duration_days)).date()
    invoice.save(update_fields=["payout_status", "due_date", "updated_at"])
    emit(
        event_type="invoice.payout.submitted",
        user=invoice.merchant.user,
        notify_admins=True,
        role_scope="merchant",
        notification={
            "category": "deposits",
            "kind": "warn",
            "title": f"Payout requested for {invoice.code}",
            "body": f"{format_usd(payout_amount)} is pending admin approval before transfer.",
            "href": f"/merchant/invoices/{invoice.id}",
        },
        invalidate=_merchant_invoice_keys(invoice)
        + [key("balance"), key("balanceTx"), key("adminLedger")],
        room=invoice_room(invoice.id),
        email="money",
        idempotency_key=f"email:invoice.payout.submitted:{invoice.id}",
        email_context={
            "amount_cents": payout_amount,
            "invoice_code": invoice.code,
        },
    )
    return invoice


@transaction.atomic
def mark_invoice_payout_settled(invoice: Invoice) -> Invoice:
    invoice = Invoice.objects.select_for_update().get(pk=invoice.pk)
    invoice.payout_status = Invoice.PayoutStatus.SETTLED
    invoice.finance_step = Invoice.FinanceStep.FUNDING_WITHDRAWN
    invoice.repayment_state = Invoice.RepaymentState.CURRENT
    if invoice.due_date is None:
        invoice.due_date = (timezone.now() + timedelta(days=invoice.duration_days)).date()
    invoice.save(
        update_fields=[
            "payout_status",
            "finance_step",
            "repayment_state",
            "due_date",
            "updated_at",
        ]
    )
    emit(
        event_type="invoice.payout.withdrawn",
        user=invoice.merchant.user,
        role_scope="merchant",
        notification={
            "category": "deposits",
            "kind": "send",
            "title": f"Funding withdrawn for {invoice.code}",
            "body": f"{format_usd(invoice.funded_amount_cents)} was sent to your payout method.",
            "href": f"/merchant/invoices/{invoice.id}",
        },
        invalidate=_merchant_invoice_keys(invoice) + [key("balance"), key("balanceTx")],
        room=invoice_room(invoice.id),
        email="money",
        idempotency_key=f"email:invoice.payout.withdrawn:{invoice.id}",
        email_context={
            "amount_cents": invoice.funded_amount_cents,
            "invoice_code": invoice.code,
        },
    )
    return invoice


@transaction.atomic
def mark_invoice_payout_failed(invoice: Invoice) -> Invoice:
    invoice = Invoice.objects.select_for_update().get(pk=invoice.pk)
    if invoice.payout_status == Invoice.PayoutStatus.PENDING:
        invoice.payout_status = Invoice.PayoutStatus.READY
        invoice.save(update_fields=["payout_status", "updated_at"])
        emit(
            event_type="invoice.payout.failed",
            user=invoice.merchant.user,
            notify_admins=True,
            role_scope="merchant",
            notification={
                "category": "deposits",
                "kind": "alert",
                "title": f"Payout failed for {invoice.code}",
                "body": "Held funds were returned. You can request withdrawal again.",
                "urgent": True,
                "href": f"/merchant/invoices/{invoice.id}",
            },
            invalidate=_merchant_invoice_keys(invoice) + [key("balance"), key("balanceTx")],
            room=invoice_room(invoice.id),
            email=False,
        )
    return invoice


def _principal_already_repaid_cents(invoice: Invoice) -> int:
    repaid = (
        BalanceTransaction.objects.filter(
            invoice_id=invoice.id,
            type=BalanceTransaction.Type.REPAYMENT,
            status=BalanceTransaction.Status.SUCCESSFUL,
        ).aggregate(s=Sum("amount_cents"))["s"]
        or 0
    )
    # Cap principal recovered at funded amount.
    return min(repaid, invoice.funded_amount_cents or 0)


def _distribute_repayment_to_pool(
    invoice: Invoice,
    amount_cents: int,
    *,
    principal_cents: int,
    interest_to_investors_cents: int,
) -> None:
    if not invoice.pool_id or amount_cents <= 0:
        return
    investor_amount = principal_cents + interest_to_investors_cents
    if investor_amount <= 0:
        return
    positions = list(
        PoolPosition.objects.select_for_update()
        .filter(pool_id=invoice.pool_id, principal_cents__gt=0)
        .select_related("investor__user")
    )
    total = sum(p.principal_cents for p in positions)
    if total <= 0 or not positions:
        return
    remaining = investor_amount
    for idx, position in enumerate(positions):
        if idx == len(positions) - 1:
            share = remaining
        else:
            share = (investor_amount * position.principal_cents) // total
            remaining -= share
        if share <= 0:
            continue
        credit_available(
            position.investor.user,
            share,
            tx_type=BalanceTransaction.Type.RETURN,
            destination_label=f"Repayment return · {invoice.code}",
            invoice=invoice,
            pool=invoice.pool,
            idempotency_key=f"repay-return-{invoice.id}-{position.id}-{amount_cents}-{share}",
        )


@transaction.atomic
def repay_invoice(invoice: Invoice, amount_cents: int, *, idempotency_key: str | None = None) -> Invoice:
    invoice = Invoice.objects.select_for_update().get(pk=invoice.pk)
    if invoice.payout_status != Invoice.PayoutStatus.SETTLED:
        raise ValidationError("Repayment unlocks after funding withdrawal settles.")
    if invoice.finance_step == Invoice.FinanceStep.FINANCE_REPAID or invoice.outstanding_cents <= 0:
        raise ValidationError("Invoice already repaid.")
    if amount_cents <= 0:
        raise ValidationError("amount_cents must be positive.")
    amount_cents = min(amount_cents, invoice.outstanding_cents)

    fees = current_fees()
    principal_left = max(0, (invoice.funded_amount_cents or 0) - _principal_already_repaid_cents(invoice))
    principal_share = min(amount_cents, principal_left)
    interest_share = amount_cents - principal_share

    platform_fee = bps_of(interest_share, fees.platform_fee_bps)
    lateness_fee = 0
    overdue = bool(invoice.due_date and invoice.due_date < timezone.now().date()) or (
        invoice.repayment_state == Invoice.RepaymentState.OVERDUE
    )
    if overdue and interest_share > 0:
        lateness_fee = bps_of(interest_share, fees.lateness_fee_bps)
    # Fees cannot exceed interest slice.
    total_fee = min(interest_share, platform_fee + lateness_fee)
    # Prefer platform fee first, then lateness.
    platform_fee = min(platform_fee, total_fee)
    lateness_fee = max(0, total_fee - platform_fee)
    interest_to_investors = interest_share - total_fee

    debit_available(
        invoice.merchant.user,
        amount_cents,
        tx_type=BalanceTransaction.Type.REPAYMENT,
        destination_label=f"Repayment {invoice.code}",
        invoice=invoice,
        pool=invoice.pool,
        idempotency_key=idempotency_key or f"repay-{invoice.id}-{invoice.outstanding_cents}-{amount_cents}",
    )
    if platform_fee:
        record_fee(
            invoice.merchant.user,
            platform_fee,
            destination_label=f"Platform fee · {invoice.code}",
            invoice=invoice,
            pool=invoice.pool,
            idempotency_key=f"repay-fee-{invoice.id}-{amount_cents}-{platform_fee}",
            debit=False,
        )
    if lateness_fee:
        record_fee(
            invoice.merchant.user,
            lateness_fee,
            destination_label=f"Lateness fee · {invoice.code}",
            invoice=invoice,
            pool=invoice.pool,
            idempotency_key=f"repay-late-{invoice.id}-{amount_cents}-{lateness_fee}",
            debit=False,
        )
    _distribute_repayment_to_pool(
        invoice,
        amount_cents,
        principal_cents=principal_share,
        interest_to_investors_cents=interest_to_investors,
    )
    invoice.outstanding_cents = max(0, invoice.outstanding_cents - amount_cents)
    if invoice.outstanding_cents == 0:
        invoice.finance_step = Invoice.FinanceStep.FINANCE_REPAID
        invoice.repayment_state = Invoice.RepaymentState.REPAID
    elif invoice.due_date and invoice.due_date < timezone.now().date():
        invoice.finance_step = Invoice.FinanceStep.FINANCE_MATURED
        invoice.repayment_state = Invoice.RepaymentState.OVERDUE
    else:
        invoice.finance_step = Invoice.FinanceStep.FINANCE_MATURED
        invoice.repayment_state = Invoice.RepaymentState.CURRENT
    invoice.save()
    emit(
        event_type="invoice.repaid",
        user=invoice.merchant.user,
        notify_admins=True,
        role_scope="merchant",
        notification={
            "category": "invoiceUpdates",
            "kind": "send",
            "title": f"Repayment posted for {invoice.code}",
            "body": f"{format_usd(amount_cents)} applied. Outstanding {format_usd(invoice.outstanding_cents)}.",
            "href": f"/merchant/invoices/{invoice.id}",
        },
        invalidate=_merchant_invoice_keys(invoice) + [key("balance"), key("balanceTx")],
        room=invoice_room(invoice.id),
        email="money",
        idempotency_key=f"email:invoice.repaid:{invoice.id}:{amount_cents}:{invoice.outstanding_cents}",
        email_context={
            "amount_cents": amount_cents,
            "invoice_code": invoice.code,
            "outstanding_cents": invoice.outstanding_cents,
        },
    )
    return invoice


@transaction.atomic
def auto_repay_user_invoices(user) -> list[Invoice]:
    """Debit available balance against settled invoices with outstanding (oldest due first)."""
    from balances.services import get_or_create_balance

    if not getattr(user, "has_merchant", False):
        return []
    balance = get_or_create_balance(user)
    available = balance.available_cents
    if available <= 0:
        return []

    qs = (
        Invoice.objects.select_for_update()
        .filter(
            merchant__user=user,
            payout_status=Invoice.PayoutStatus.SETTLED,
            outstanding_cents__gt=0,
        )
        .exclude(finance_step=Invoice.FinanceStep.FINANCE_REPAID)
        .order_by("due_date", "created_at")
    )
    repaid: list[Invoice] = []
    for invoice in qs:
        if available <= 0:
            break
        # Refresh available inside loop via balance lock in debit.
        from balances.models import Balance

        bal = Balance.objects.select_for_update().filter(user=user).first()
        available = bal.available_cents if bal else 0
        if available <= 0:
            break
        take = min(available, invoice.outstanding_cents)
        if take <= 0:
            continue
        try:
            repay_invoice(
                invoice,
                take,
                idempotency_key=f"auto-repay-{invoice.id}-{invoice.outstanding_cents}-{take}",
            )
            repaid.append(invoice)
        except ValidationError:
            continue
    return repaid


@transaction.atomic
def mark_overdue_invoices() -> int:
    today = timezone.now().date()
    updated = 0
    qs = Invoice.objects.filter(
        payout_status=Invoice.PayoutStatus.SETTLED,
        outstanding_cents__gt=0,
        due_date__lt=today,
    ).exclude(
        repayment_state__in=[Invoice.RepaymentState.REPAID, Invoice.RepaymentState.OVERDUE]
    )
    for invoice in qs.iterator():
        Invoice.objects.filter(pk=invoice.pk).update(
            repayment_state=Invoice.RepaymentState.OVERDUE,
            finance_step=Invoice.FinanceStep.FINANCE_MATURED,
            updated_at=timezone.now(),
        )
        updated += 1
    return updated

