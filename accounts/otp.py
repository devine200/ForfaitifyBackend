"""Local email OTP issue and check. Delivery uses the transactional mail helper."""

from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.utils import timezone

from accounts.models import EmailOtp
from notifications.email_service import first_name, render_email, send_multipart_email

logger = logging.getLogger("forfaitify.otp")

OTP_TTL = timedelta(minutes=10)
MAX_ATTEMPTS = 5
MAX_SENDS_PER_HOUR = 5


class OtpError(Exception):
    def __init__(self, message: str, *, code: str = "otp_invalid"):
        super().__init__(message)
        self.code = code


def _hash_code(code: str) -> str:
    material = f"{settings.SECRET_KEY}:{code}".encode()
    return hashlib.sha256(material).hexdigest()


def _send_key(email: str, purpose: str) -> str:
    return f"otp:send:{purpose}:{email}"


def _assert_send_allowed(email: str, purpose: str) -> None:
    key = _send_key(email, purpose)
    sent = cache.get(key) or 0
    if sent >= MAX_SENDS_PER_HOUR:
        raise OtpError(
            "Too many codes sent. Try again in an hour.",
            code="otp_rate_limited",
        )


def _bump_send(email: str, purpose: str) -> None:
    key = _send_key(email, purpose)
    try:
        cache.incr(key)
    except ValueError:
        cache.set(key, 1, timeout=3600)


def _deliver(email: str, purpose: str, code: str) -> None:
    User = get_user_model()
    user = User.objects.filter(email__iexact=email).first()
    name = first_name(user.full_name) if user else ""
    if user and getattr(user, "has_investor", False) and not getattr(user, "has_merchant", False):
        role_scope = "investor"
    else:
        role_scope = "merchant"
    if purpose == EmailOtp.Purpose.SIGNUP:
        subject = "Your Forfaitify verification code"
        headline = "Confirm your email"
        body = (
            "Use the code below to finish creating your Forfaitify account. "
            "It expires in 10 minutes and works only once. "
            "If you did not start this signup, you can ignore this email."
        )
        eyebrow = "Account"
        why = "You are receiving this because a Forfaitify account was started with this email address."
        show_prefs = False
        support_path = "/contact"
    else:
        subject = "Your Forfaitify password reset code"
        headline = "Reset your password"
        body = (
            "Use the code below to choose a new password. "
            "It expires in 10 minutes and works only once. "
            "If you did not ask to reset your password, you can ignore this email and your password will stay the same."
        )
        eyebrow = "Security"
        why = "You are receiving this because a password reset was requested for your Forfaitify account."
        show_prefs = True
        support_path = ""
    _subject, html, text = render_email(
        email_bucket="money",
        title=headline,
        body=body,
        context={
            "subject": subject,
            "headline": headline,
            "eyebrow": eyebrow,
            "preheader": "This code expires in 10 minutes.",
            "why": why,
            "code": code,
            "show_prefs": show_prefs,
            "support_url": support_path or None,
            "href": "",
        },
        recipient_name=name,
        role_scope=role_scope,
    )
    send_multipart_email(
        to_email=email,
        subject=_subject,
        html=html,
        text=text,
        client_reference=f"otp:{purpose}",
    )


def issue_otp(email: str, purpose: str) -> None:
    email = email.strip().lower()
    _assert_send_allowed(email, purpose)
    code = f"{secrets.randbelow(1_000_000):06d}"
    EmailOtp.objects.filter(email=email, purpose=purpose, consumed_at__isnull=True).update(
        consumed_at=timezone.now()
    )
    EmailOtp.objects.create(
        email=email,
        purpose=purpose,
        code_hash=_hash_code(code),
        expires_at=timezone.now() + OTP_TTL,
    )
    try:
        _deliver(email, purpose, code)
    except Exception:
        logger.exception("OTP delivery failed email=%s purpose=%s", email, purpose)
        EmailOtp.objects.filter(email=email, purpose=purpose, consumed_at__isnull=True).update(
            consumed_at=timezone.now()
        )
        raise
    logger.info("OTP delivered email=%s purpose=%s", email, purpose)
    _bump_send(email, purpose)


def verify_otp(email: str, purpose: str, code: str, *, consume: bool) -> None:
    email = email.strip().lower()
    now = timezone.now()
    row = (
        EmailOtp.objects.filter(email=email, purpose=purpose, consumed_at__isnull=True, expires_at__gt=now)
        .order_by("-created_at")
        .first()
    )
    if row is None:
        raise OtpError("Invalid or expired code.")
    if row.attempts >= MAX_ATTEMPTS:
        row.consumed_at = now
        row.save(update_fields=["consumed_at", "updated_at"])
        raise OtpError("Too many attempts. Request a new code.", code="otp_locked")
    if not secrets.compare_digest(row.code_hash, _hash_code(code.strip())):
        row.attempts += 1
        if row.attempts >= MAX_ATTEMPTS:
            row.consumed_at = now
        row.save(update_fields=["attempts", "consumed_at", "updated_at"])
        raise OtpError("Invalid or expired code.")
    if consume:
        row.consumed_at = now
        row.save(update_fields=["consumed_at", "updated_at"])
