from datetime import timedelta

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from balances.models import BalanceTransaction
from balances.services import credit_available, debit_available
from epochs.models import Epoch
from notifications.emit import emit
from notifications.formatting import format_usd
from notifications.keys import key
from pools.models import Pool, PoolPosition, PoolWithdrawalRequest


@transaction.atomic
def deposit_into_pool(pool: Pool, investor, amount_cents: int, *, idempotency_key: str | None = None):
    if pool.closed or pool.status != Pool.Status.ACTIVE:
        raise ValidationError("Pool is not accepting deposits.")
    if amount_cents < pool.min_deposit_cents:
        raise ValidationError(f"Minimum deposit is {pool.min_deposit_cents} cents.")

    debit_available(
        investor.user,
        amount_cents,
        tx_type=BalanceTransaction.Type.POOL_ALLOCATE,
        destination_label=f"Pool deposit · {pool.name}",
        pool=pool,
        idempotency_key=idempotency_key,
    )
    position, _ = PoolPosition.objects.select_for_update().get_or_create(
        pool=pool,
        investor=investor,
        defaults={"principal_cents": 0},
    )
    position.principal_cents += amount_cents
    position.save(update_fields=["principal_cents", "updated_at"])
    emit(
        event_type="pool.deposit",
        user=investor.user,
        role_scope="investor",
        notification={
            "category": "poolMatching",
            "kind": "send",
            "title": f"Deposited {format_usd(amount_cents)} into {pool.name}",
            "body": "Your pool position was updated.",
            "href": f"/investor/pools/{pool.id}",
        },
        invalidate=[
            key("balance"),
            key("balanceTx"),
            key("pools"),
            key("pool", str(pool.id)),
            key("investorDashboard"),
            key("notifications"),
        ],
        email="investment",
        idempotency_key=f"email:pool.deposit:{idempotency_key or position.id}:{amount_cents}",
        email_context={"amount_cents": amount_cents, "pool_name": pool.name},
    )
    return position


@transaction.atomic
def request_pool_withdrawal(pool: Pool, investor, amount_cents: int) -> PoolWithdrawalRequest:
    position = PoolPosition.objects.filter(pool=pool, investor=investor).first()
    if not position or position.principal_cents < amount_cents:
        raise ValidationError("Insufficient pool position.")
    total_principal = (
        PoolPosition.objects.filter(pool=pool).aggregate(s=Sum("principal_cents"))["s"] or 0
    )
    share_bps = int((position.principal_cents / total_principal) * 10000) if total_principal else 0
    req = PoolWithdrawalRequest.objects.create(
        pool=pool,
        investor=investor,
        amount_cents=amount_cents,
        pool_share_bps_snapshot=share_bps,
    )
    emit(
        event_type="pool.withdrawal.requested",
        user=investor.user,
        notify_admins=True,
        role_scope="investor",
        notification={
            "category": "poolMatching",
            "kind": "warn",
            "title": f"Pool withdrawal requested · {pool.name}",
            "body": f"{format_usd(amount_cents)} is awaiting a decision.",
            "href": f"/investor/pools/{pool.id}",
        },
        invalidate=[
            key("pools"),
            key("pool", str(pool.id)),
            key("investorDashboard"),
            key("adminDashboard"),
            key("notifications"),
        ],
        email="investment",
        idempotency_key=f"email:pool.withdrawal.requested:{req.id}",
        email_context={"amount_cents": amount_cents, "pool_name": pool.name},
    )
    return req


@transaction.atomic
def decide_pool_withdrawal(req: PoolWithdrawalRequest, decision: str) -> PoolWithdrawalRequest:
    if req.status != PoolWithdrawalRequest.Status.PENDING:
        raise ValidationError("Request is not pending.")
    if decision == "accept":
        req.status = PoolWithdrawalRequest.Status.ACCEPTED
    elif decision == "reject":
        req.status = PoolWithdrawalRequest.Status.REJECTED
    else:
        raise ValidationError("decision must be accept or reject.")
    req.save(update_fields=["status", "updated_at"])
    emit(
        event_type="pool.withdrawal.decided",
        user=req.investor.user,
        notify_admins=True,
        role_scope="investor",
        notification={
            "category": "poolMatching",
            "kind": "send" if decision == "accept" else "alert",
            "title": f"Pool withdrawal {decision}ed · {req.pool.name}",
            "body": f"Your request for {format_usd(req.amount_cents)} was {decision}ed.",
            "href": f"/investor/pools/{req.pool_id}",
        },
        invalidate=[
            key("pools"),
            key("pool", str(req.pool_id)),
            key("investorDashboard"),
            key("adminDashboard"),
            key("notifications"),
        ],
        email="investment",
        idempotency_key=f"email:pool.withdrawal.decided:{req.id}:{decision}",
        email_context={
            "amount_cents": req.amount_cents,
            "pool_name": req.pool.name,
            "decision": decision,
        },
    )
    return req


@transaction.atomic
def settle_pool_withdrawal(req: PoolWithdrawalRequest) -> PoolWithdrawalRequest:
    if req.status != PoolWithdrawalRequest.Status.ACCEPTED:
        raise ValidationError("Request must be accepted before settle.")
    position = PoolPosition.objects.select_for_update().get(pool=req.pool, investor=req.investor)
    if position.principal_cents < req.amount_cents:
        raise ValidationError("Position too low to settle.")
    position.principal_cents -= req.amount_cents
    position.save(update_fields=["principal_cents", "updated_at"])
    credit_available(
        req.investor.user,
        req.amount_cents,
        tx_type=BalanceTransaction.Type.POOL_WITHDRAW,
        destination_label=f"Pool withdrawal · {req.pool.name}",
        pool=req.pool,
        idempotency_key=f"pool-wdr-settle-{req.id}",
    )
    req.status = PoolWithdrawalRequest.Status.SETTLED
    req.save(update_fields=["status", "updated_at"])
    emit(
        event_type="pool.withdrawal.settled",
        user=req.investor.user,
        role_scope="investor",
        notification={
            "category": "deposits",
            "kind": "send",
            "title": f"Pool withdrawal settled · {req.pool.name}",
            "body": f"{format_usd(req.amount_cents)} returned to your available balance.",
            "href": "/investor/balance",
        },
        invalidate=[
            key("balance"),
            key("balanceTx"),
            key("pools"),
            key("pool", str(req.pool_id)),
            key("investorDashboard"),
            key("notifications"),
        ],
        email="money",
        idempotency_key=f"email:pool.withdrawal.settled:{req.id}",
        email_context={"amount_cents": req.amount_cents, "pool_name": req.pool.name},
    )
    return req


def ensure_current_epoch(pool: Pool, duration_days: int = 14) -> Epoch:
    current = pool.epochs.exclude(state=Epoch.State.CLOSED).order_by("-index").first()
    if current:
        return current
    last = pool.epochs.order_by("-index").first()
    index = (last.index + 1) if last else 1
    start = timezone.now()
    end = start + timedelta(days=duration_days)
    return Epoch.objects.create(
        pool=pool,
        index=index,
        starts_at=start,
        ends_at=end,
        withdrawal_window_start=end - timedelta(days=3),
        withdrawal_window_end=end,
        state=Epoch.State.FUNDING_OPEN,
    )
