"""Domain event spine: in-app notification + WS invalidate + Celery email handoff."""

from __future__ import annotations

import logging
from typing import Any, Iterable, Literal

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from accounts.models import NotificationPreference
from notifications.categories import ALWAYS_ON, EMAIL_BUCKETS
from notifications.keys import normalize_keys
from notifications.models import Notification
from notifications.serializers import NotificationSerializer

logger = logging.getLogger(__name__)
User = get_user_model()

EmailBucket = Literal["money", "cosign", "investment"] | bool


def user_group(user_id) -> str:
    return f"user.{user_id}"


def admin_group() -> str:
    return "role.admin"


def invoice_room(invoice_id) -> str:
    return f"invoice.{invoice_id}"


def ticket_room(ticket_id) -> str:
    return f"ticket.{ticket_id}"


def resolve_role_scope(user, preferred: str | None = None) -> str:
    if preferred:
        return preferred
    if getattr(user, "is_admin", False):
        return Notification.RoleScope.ADMIN
    if getattr(user, "has_merchant", False):
        return Notification.RoleScope.MERCHANT
    if getattr(user, "has_investor", False):
        return Notification.RoleScope.INVESTOR
    return Notification.RoleScope.MERCHANT


def prefs_allow(user, role_scope: str, category: str) -> bool:
    if category in ALWAYS_ON:
        return True
    pref = NotificationPreference.objects.filter(
        user=user, role_scope=role_scope, category=category
    ).first()
    if pref is None:
        return True
    return pref.enabled


def _group_send(group: str, message: dict) -> None:
    layer = get_channel_layer()
    if layer is None:
        logger.warning("No channel layer configured; skipping live push to %s", group)
        return
    async_to_sync(layer.group_send)(group, {"type": "live.event", "message": message})


def _publish(
    *,
    user_ids: Iterable,
    notify_admins: bool,
    room: str | None,
    invalidate: list[dict[str, str]],
    notification_payload: dict | None,
) -> None:
    ts = timezone.now().isoformat()
    if invalidate:
        inv_msg = {"v": 1, "type": "invalidate", "ts": ts, "data": {"keys": invalidate}}
        for uid in set(str(u) for u in user_ids):
            _group_send(user_group(uid), inv_msg)
        if notify_admins:
            _group_send(admin_group(), inv_msg)
        if room:
            _group_send(room, inv_msg)
    if notification_payload:
        n_msg = {
            "v": 1,
            "type": "notification.created",
            "ts": ts,
            "data": notification_payload,
        }
        uid = notification_payload.get("user_id")
        if uid:
            _group_send(user_group(uid), n_msg)
        if notify_admins and notification_payload.get("role_scope") == "admin":
            _group_send(admin_group(), n_msg)


def emit(
    *,
    event_type: str,
    user=None,
    users: Iterable | None = None,
    notify_admins: bool = False,
    role_scope: str | None = None,
    notification: dict[str, Any] | None = None,
    invalidate: list | None = None,
    email: EmailBucket = False,
    email_to: str | None = None,
    idempotency_key: str | None = None,
    room: str | None = None,
    email_context: dict[str, Any] | None = None,
) -> Notification | None:
    """
    Persist optional notification, then after commit push WS invalidate and enqueue email.
    """
    recipient_ids: list = []
    if user is not None:
        recipient_ids.append(user.id)
    for u in users or []:
        recipient_ids.append(getattr(u, "id", u))

    if notify_admins:
        admin_ids = list(
            User.objects.filter(is_admin=True, is_active=True).values_list("id", flat=True)
        )
        recipient_ids.extend(admin_ids)

    keys = normalize_keys(invalidate)
    created: Notification | None = None
    notif_payload: dict | None = None

    if notification and user is not None:
        scope = resolve_role_scope(user, role_scope)
        category = notification.get("category", "securityAlerts")
        if prefs_allow(user, scope, category):
            created = Notification.objects.create(
                user=user,
                role_scope=scope,
                category=category,
                kind=notification.get("kind", Notification.Kind.SEND),
                title=notification["title"],
                body=notification.get("body", ""),
                urgent=bool(notification.get("urgent", False)),
                href=notification.get("href", ""),
            )
            data = NotificationSerializer(created).data
            notif_payload = {**data, "user_id": str(user.id)}
            if "notifications" not in {k["key"] for k in keys}:
                keys.append({"key": "notifications"})

    if notify_admins and notification and user is None:
        # Admin-only ops notification to each admin
        for admin in User.objects.filter(is_admin=True, is_active=True):
            category = notification.get("category", "operations")
            if not prefs_allow(admin, Notification.RoleScope.ADMIN, category):
                # admin prefs may not exist — still create
                pass
            n = Notification.objects.create(
                user=admin,
                role_scope=Notification.RoleScope.ADMIN,
                category=category,
                kind=notification.get("kind", Notification.Kind.WARN),
                title=notification["title"],
                body=notification.get("body", ""),
                urgent=bool(notification.get("urgent", False)),
                href=notification.get("href", ""),
            )
            if created is None:
                created = n
            data = NotificationSerializer(n).data
            notif_payload = {**data, "user_id": str(admin.id)}
            if "notifications" not in {k["key"] for k in keys}:
                keys.append({"key": "notifications"})

    email_bucket: str | None = None
    if email is True:
        email_bucket = "money"
    elif isinstance(email, str) and email in EMAIL_BUCKETS:
        email_bucket = email

    def _after_commit():
        _publish(
            user_ids=recipient_ids,
            notify_admins=notify_admins,
            room=room,
            invalidate=keys,
            notification_payload=notif_payload,
        )
        if email_bucket or email_to:
            from notifications.tasks import enqueue_email

            enqueue_email.delay(
                event_type=event_type,
                email_bucket=email_bucket or "cosign",
                notification_id=str(created.id) if created else None,
                user_id=str(user.id) if user is not None else None,
                email_to=email_to,
                idempotency_key=idempotency_key
                or (
                    f"email:{event_type}:{created.id}"
                    if created
                    else f"email:{event_type}:{email_to or 'unknown'}"
                ),
                context=email_context or {},
            )

    transaction.on_commit(_after_commit)
    return created


# Back-compat thin wrapper
def notify(user, *, role_scope: str, category: str, title: str, body: str, kind="send", urgent=False, href=""):
    return emit(
        event_type="legacy.notify",
        user=user,
        role_scope=role_scope,
        notification={
            "category": category,
            "title": title,
            "body": body,
            "kind": kind,
            "urgent": urgent,
            "href": href,
        },
        invalidate=[{"key": "notifications"}],
        email=False,
    )
