from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from balances.models import Balance, BalanceTransaction


def get_or_create_balance(user) -> Balance:
    balance, _ = Balance.objects.get_or_create(
        user=user,
        defaults={"currency": getattr(settings, "DEFAULT_CURRENCY", "NGN")},
    )
    return balance


@transaction.atomic
def credit_available(
    user,
    amount_cents: int,
    *,
    tx_type: str,
    destination_label: str = "",
    invoice=None,
    pool=None,
    payment_intent=None,
    idempotency_key: str | None = None,
    status: str = BalanceTransaction.Status.SUCCESSFUL,
) -> BalanceTransaction:
    if amount_cents <= 0:
        raise ValidationError("amount_cents must be positive.")
    if idempotency_key:
        existing = BalanceTransaction.objects.filter(idempotency_key=idempotency_key).first()
        if existing:
            return existing

    balance = Balance.objects.select_for_update().get(pk=get_or_create_balance(user).pk)
    if status == BalanceTransaction.Status.SUCCESSFUL:
        balance.available_cents += amount_cents
        balance.save(update_fields=["available_cents", "updated_at"])

    return BalanceTransaction.objects.create(
        balance=balance,
        type=tx_type,
        status=status,
        amount_cents=amount_cents,
        destination_label=destination_label,
        invoice=invoice,
        pool=pool,
        payment_intent=payment_intent,
        idempotency_key=idempotency_key,
    )


@transaction.atomic
def debit_available(
    user,
    amount_cents: int,
    *,
    tx_type: str,
    destination_label: str = "",
    invoice=None,
    pool=None,
    payment_intent=None,
    idempotency_key: str | None = None,
    hold: bool = False,
) -> BalanceTransaction:
    if amount_cents <= 0:
        raise ValidationError("amount_cents must be positive.")
    if idempotency_key:
        existing = BalanceTransaction.objects.filter(idempotency_key=idempotency_key).first()
        if existing:
            return existing

    balance = Balance.objects.select_for_update().get(pk=get_or_create_balance(user).pk)
    if balance.available_cents < amount_cents:
        raise ValidationError("Insufficient available balance.")

    balance.available_cents -= amount_cents
    if hold:
        balance.held_cents += amount_cents
    balance.save(update_fields=["available_cents", "held_cents", "updated_at"])

    return BalanceTransaction.objects.create(
        balance=balance,
        type=tx_type,
        status=BalanceTransaction.Status.SUCCESSFUL
        if not hold
        else BalanceTransaction.Status.PENDING,
        amount_cents=amount_cents,
        destination_label=destination_label,
        invoice=invoice,
        pool=pool,
        payment_intent=payment_intent,
        idempotency_key=idempotency_key,
    )


def _pending_hold_tx(*, payment_intent, amount_cents: int) -> BalanceTransaction:
    tx = (
        BalanceTransaction.objects.select_for_update()
        .filter(
            payment_intent=payment_intent,
            status=BalanceTransaction.Status.PENDING,
            amount_cents=amount_cents,
        )
        .order_by("created_at")
        .first()
    )
    if not tx:
        raise ValidationError("No matching held funds for this payment.")
    return tx


@transaction.atomic
def release_hold_for_intent(payment_intent) -> BalanceTransaction:
    """Finalize a hold after a successful payout/transfer (funds leave the platform)."""
    tx = _pending_hold_tx(payment_intent=payment_intent, amount_cents=payment_intent.amount_cents)
    balance = Balance.objects.select_for_update().get(pk=tx.balance_id)
    if balance.held_cents < tx.amount_cents:
        raise ValidationError("Held balance is lower than the pending hold.")
    balance.held_cents -= tx.amount_cents
    balance.save(update_fields=["held_cents", "updated_at"])
    tx.status = BalanceTransaction.Status.SUCCESSFUL
    tx.save(update_fields=["status", "updated_at"])
    return tx


@transaction.atomic
def reject_hold_for_intent(payment_intent) -> BalanceTransaction:
    """Return held funds to available after a rejected/failed payout."""
    tx = _pending_hold_tx(payment_intent=payment_intent, amount_cents=payment_intent.amount_cents)
    balance = Balance.objects.select_for_update().get(pk=tx.balance_id)
    if balance.held_cents < tx.amount_cents:
        raise ValidationError("Held balance is lower than the pending hold.")
    balance.held_cents -= tx.amount_cents
    balance.available_cents += tx.amount_cents
    balance.save(update_fields=["held_cents", "available_cents", "updated_at"])
    tx.status = BalanceTransaction.Status.REJECTED
    tx.save(update_fields=["status", "updated_at"])
    return tx


# Back-compat wrappers used by older call sites / seeds.
@transaction.atomic
def release_hold_to_settled(user, amount_cents: int, *, payment_intent=None):
    if payment_intent is not None:
        return release_hold_for_intent(payment_intent)
    balance = Balance.objects.select_for_update().get(pk=get_or_create_balance(user).pk)
    if balance.held_cents < amount_cents:
        raise ValidationError("Held balance is lower than the release amount.")
    balance.held_cents -= amount_cents
    balance.save(update_fields=["held_cents", "updated_at"])
    return balance


@transaction.atomic
def reject_hold(user, amount_cents: int, *, payment_intent=None):
    if payment_intent is not None:
        return reject_hold_for_intent(payment_intent)
    balance = Balance.objects.select_for_update().get(pk=get_or_create_balance(user).pk)
    if balance.held_cents < amount_cents:
        raise ValidationError("Held balance is lower than the reject amount.")
    balance.held_cents -= amount_cents
    balance.available_cents += amount_cents
    balance.save(update_fields=["held_cents", "available_cents", "updated_at"])
    return balance


def try_auto_repay_after_credit(user) -> list:
    """Best-effort: apply available balance to open invoice debts (imported lazily)."""
    from invoices.services import auto_repay_user_invoices

    return auto_repay_user_invoices(user)
