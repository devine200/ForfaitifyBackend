from notifications.emit import emit
from notifications.keys import key
from pools.models import PoolPosition


def emit_epoch_advanced(epoch) -> None:
    investors = [
        p.investor.user
        for p in PoolPosition.objects.filter(pool=epoch.pool).select_related("investor__user")
    ]
    for user in investors:
        emit(
            event_type="epoch.advanced",
            user=user,
            role_scope="investor",
            notification={
                "category": "epochEvents",
                "kind": "warn",
                "title": f"Epoch {epoch.index} → {epoch.state}",
                "body": f"{epoch.pool.name} moved to {epoch.get_state_display()}.",
                "href": f"/investor/pools/{epoch.pool_id}",
            },
            invalidate=[
                key("investorDashboard"),
                key("pools"),
                key("pool", str(epoch.pool_id)),
                key("notifications"),
            ],
            email="investment",
            idempotency_key=f"email:epoch.advanced:{epoch.id}:{epoch.state}",
            email_context={
                "pool_name": epoch.pool.name,
                "epoch_index": str(epoch.index),
                "state_label": epoch.get_state_display(),
            },
        )
