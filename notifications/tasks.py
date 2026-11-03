from __future__ import annotations

import logging

from celery import shared_task
from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.utils import timezone

from notifications.email_service import absolute_href, first_name, links_for_role, render_email, send_multipart_email
from notifications.guardrails import (
    bump_user_rate_limit,
    check_user_rate_limit,
    circuit_is_open,
    record_provider_failure,
    record_provider_success,
)
from notifications.models import EmailDelivery, Notification

logger = logging.getLogger(__name__)
User = get_user_model()


@shared_task(ignore_result=True)
def enqueue_email(
    *,
    event_type: str,
    email_bucket: str,
    notification_id: str | None = None,
    user_id: str | None = None,
    email_to: str | None = None,
    idempotency_key: str,
    context: dict | None = None,
):
    """Fast path: prefs, dedup, rate limits, then hand off to send_email."""
    if circuit_is_open():
        EmailDelivery.objects.update_or_create(
            idempotency_key=idempotency_key,
            defaults={
                "to_email": email_to or "",
                "event_type": event_type,
                "status": EmailDelivery.Status.CIRCUIT_OPEN,
                "error": "Circuit open",
            },
        )
        return {"status": "circuit_open"}

    if EmailDelivery.objects.filter(
        idempotency_key=idempotency_key,
        status=EmailDelivery.Status.SENT,
    ).exists():
        return {"status": "skipped_dedup"}

    notification = None
    user = None
    to_email = email_to or ""
    category = ""
    title = context.get("title") if context else None
    body = context.get("body") if context else None
    href = (context or {}).get("href", "")

    if notification_id:
        notification = Notification.objects.filter(pk=notification_id).select_related("user").first()
        if notification:
            user = notification.user
            to_email = to_email or user.email
            category = notification.category
            title = title or notification.title
            body = body or notification.body
            href = href or notification.href

    if user_id and user is None:
        user = User.objects.filter(pk=user_id).first()
        if user and not to_email:
            to_email = user.email

    if not to_email or not title:
        logger.warning("enqueue_email missing to_email/title for %s", event_type)
        return {"status": "skipped_invalid"}

    mailed_to_someone_else = bool(email_to) and (
        user is None or email_to.strip().lower() != (user.email or "").lower()
    )
    if mailed_to_someone_else:
        named = (context or {}).get("recipient_name") or (context or {}).get("invitee_name") or ""
        recipient_name = first_name(named)
        role_scope = ""
    else:
        recipient_name = first_name(user.full_name) if user else ""
        role_scope = notification.role_scope if notification else ""
        if not role_scope and user is not None:
            role_scope = "investor" if getattr(user, "has_investor", False) and not getattr(user, "has_merchant", False) else "merchant"

    user_key = str(user.id) if user else to_email.lower()
    if not check_user_rate_limit(user_key):
        EmailDelivery.objects.update_or_create(
            idempotency_key=idempotency_key,
            defaults={
                "to_email": to_email,
                "user": user,
                "event_type": event_type,
                "category": category,
                "notification": notification,
                "status": EmailDelivery.Status.RATE_LIMITED,
            },
        )
        return {"status": "rate_limited"}

    try:
        delivery, created = EmailDelivery.objects.get_or_create(
            idempotency_key=idempotency_key,
            defaults={
                "to_email": to_email,
                "user": user,
                "event_type": event_type,
                "category": category,
                "notification": notification,
                "status": EmailDelivery.Status.PENDING,
                "template_name": f"email/{email_bucket}/generic.html",
            },
        )
    except IntegrityError:
        return {"status": "skipped_dedup"}

    if not created and delivery.status == EmailDelivery.Status.SENT:
        return {"status": "skipped_dedup"}

    send_email.apply_async(
        kwargs={
            "delivery_id": str(delivery.id),
            "email_bucket": email_bucket,
            "to_email": to_email,
            "title": title,
            "body": body or "",
            "href": href or "",
            "context": context or {},
            "user_key": user_key,
            "event_type": event_type,
            "recipient_name": recipient_name,
            "role_scope": role_scope,
        }
    )
    return {"status": "enqueued", "delivery_id": str(delivery.id)}


@shared_task(
    bind=True,
    ignore_result=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
    max_retries=5,
    rate_limit="30/m",
)
def send_email(
    self,
    *,
    delivery_id: str,
    email_bucket: str,
    to_email: str,
    title: str,
    body: str,
    href: str = "",
    context: dict | None = None,
    user_key: str = "",
    event_type: str = "",
    recipient_name: str = "",
    role_scope: str = "merchant",
):
    if circuit_is_open():
        EmailDelivery.objects.filter(pk=delivery_id).update(
            status=EmailDelivery.Status.CIRCUIT_OPEN,
            error="Circuit open",
        )
        return {"status": "circuit_open"}

    delivery = EmailDelivery.objects.filter(pk=delivery_id).first()
    if delivery and delivery.status == EmailDelivery.Status.SENT:
        return {"status": "skipped_dedup"}

    try:
        subject, html, text = render_email(
            email_bucket=email_bucket,
            title=title,
            body=body,
            href=href,
            context=context,
            event_type=event_type,
            recipient_name=recipient_name,
            role_scope=role_scope,
        )
        prefs_path, _support_path = links_for_role(role_scope or "merchant")
        provider_id = send_multipart_email(
            to_email=to_email,
            subject=subject,
            html=html,
            text=text,
            client_reference=str(delivery_id),
            unsubscribe_url=absolute_href(prefs_path) if role_scope else "",
        )
        EmailDelivery.objects.filter(pk=delivery_id).update(
            status=EmailDelivery.Status.SENT,
            sent_at=timezone.now(),
            provider_message_id=provider_id or "",
            error="",
            template_name=f"email/{email_bucket}/generic.html",
        )
        if user_key:
            bump_user_rate_limit(user_key)
        record_provider_success()
        return {"status": "sent"}
    except Exception as exc:
        record_provider_failure()
        EmailDelivery.objects.filter(pk=delivery_id).update(
            status=EmailDelivery.Status.FAILED,
            error=str(exc)[:2000],
        )
        raise
