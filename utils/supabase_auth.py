"""Supabase Auth client. Falls back to local stub when AUTH_STUB_MODE is True."""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from typing import Any

import httpx
from django.conf import settings
from django.core.cache import cache


@dataclass
class AuthResult:
    success: bool
    supabase_uid: str | None = None
    email: str | None = None
    message: str = ""
    raw: dict[str, Any] | None = None


def _stub_otp_key(email: str) -> str:
    return f"stub_otp:{email.strip().lower()}"


def _stub_password_key(email: str) -> str:
    return f"stub_pwd:{email.strip().lower()}"


def _hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def _configured() -> bool:
    return bool(settings.SUPABASE_URL and settings.SUPABASE_ANON_KEY)


def _headers(service: bool = False) -> dict[str, str]:
    key = (
        settings.SUPABASE_SERVICE_ROLE_KEY
        if service and settings.SUPABASE_SERVICE_ROLE_KEY
        else settings.SUPABASE_ANON_KEY
    )
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


def sign_up(email: str, password: str) -> AuthResult:
    email = email.strip().lower()
    if settings.AUTH_STUB_MODE or not _configured():
        otp = "123456"
        cache.set(_stub_otp_key(email), otp, timeout=600)
        cache.set(_stub_password_key(email), _hash_password(password), timeout=None)
        uid = f"stub-{hashlib.md5(email.encode()).hexdigest()[:16]}"
        return AuthResult(
            success=True,
            supabase_uid=uid,
            email=email,
            message="Stub OTP sent (use 123456).",
            raw={"stub": True, "otp": otp},
        )

    url = f"{settings.SUPABASE_URL.rstrip('/')}/auth/v1/signup"
    with httpx.Client(timeout=20) as client:
        resp = client.post(
            url,
            headers=_headers(),
            json={"email": email, "password": password},
        )
    data = resp.json() if resp.content else {}
    if resp.status_code >= 400:
        return AuthResult(success=False, message=data.get("msg") or data.get("error_description") or "Signup failed.", raw=data)
    user = data.get("user") or data
    return AuthResult(
        success=True,
        supabase_uid=user.get("id"),
        email=email,
        message="Verification email/OTP sent.",
        raw=data,
    )


def verify_email_otp(email: str, otp: str) -> AuthResult:
    email = email.strip().lower()
    if settings.AUTH_STUB_MODE or not _configured():
        expected = cache.get(_stub_otp_key(email))
        if expected and secrets.compare_digest(str(expected), str(otp)):
            cache.delete(_stub_otp_key(email))
            uid = f"stub-{hashlib.md5(email.encode()).hexdigest()[:16]}"
            return AuthResult(success=True, supabase_uid=uid, email=email, message="Verified.")
        return AuthResult(success=False, message="Invalid or expired OTP.")

    url = f"{settings.SUPABASE_URL.rstrip('/')}/auth/v1/verify"
    with httpx.Client(timeout=20) as client:
        resp = client.post(
            url,
            headers=_headers(),
            json={"email": email, "token": otp, "type": "signup"},
        )
    data = resp.json() if resp.content else {}
    if resp.status_code >= 400:
        return AuthResult(success=False, message=data.get("msg") or "OTP verification failed.", raw=data)
    user = data.get("user") or {}
    return AuthResult(
        success=True,
        supabase_uid=user.get("id"),
        email=email,
        message="Verified.",
        raw=data,
    )


def resend_otp(email: str) -> AuthResult:
    email = email.strip().lower()
    if settings.AUTH_STUB_MODE or not _configured():
        otp = "123456"
        cache.set(_stub_otp_key(email), otp, timeout=600)
        return AuthResult(success=True, email=email, message="Stub OTP resent (use 123456).", raw={"otp": otp})

    url = f"{settings.SUPABASE_URL.rstrip('/')}/auth/v1/resend"
    with httpx.Client(timeout=20) as client:
        resp = client.post(
            url,
            headers=_headers(),
            json={"email": email, "type": "signup"},
        )
    data = resp.json() if resp.content else {}
    if resp.status_code >= 400:
        return AuthResult(success=False, message=data.get("msg") or "Resend failed.", raw=data)
    return AuthResult(success=True, email=email, message="OTP resent.", raw=data)


def sign_in(email: str, password: str) -> AuthResult:
    email = email.strip().lower()
    if settings.AUTH_STUB_MODE or not _configured():
        stored = cache.get(_stub_password_key(email))
        # Allow login for users created outside stub cache (e.g. admin command)
        if stored is None or secrets.compare_digest(stored, _hash_password(password)):
            if stored is None:
                cache.set(_stub_password_key(email), _hash_password(password), timeout=None)
            uid = f"stub-{hashlib.md5(email.encode()).hexdigest()[:16]}"
            return AuthResult(success=True, supabase_uid=uid, email=email, message="Signed in.")
        return AuthResult(success=False, message="Invalid email or password.")

    url = f"{settings.SUPABASE_URL.rstrip('/')}/auth/v1/token?grant_type=password"
    with httpx.Client(timeout=20) as client:
        resp = client.post(
            url,
            headers=_headers(),
            json={"email": email, "password": password},
        )
    data = resp.json() if resp.content else {}
    if resp.status_code >= 400:
        return AuthResult(success=False, message=data.get("error_description") or "Login failed.", raw=data)
    user = data.get("user") or {}
    return AuthResult(
        success=True,
        supabase_uid=user.get("id"),
        email=email,
        message="Signed in.",
        raw=data,
    )


def request_password_reset(email: str) -> AuthResult:
    email = email.strip().lower()
    if settings.AUTH_STUB_MODE or not _configured():
        otp = "123456"
        cache.set(_stub_otp_key(email), otp, timeout=600)
        return AuthResult(success=True, email=email, message="Stub reset OTP sent (use 123456).", raw={"otp": otp})

    url = f"{settings.SUPABASE_URL.rstrip('/')}/auth/v1/recover"
    with httpx.Client(timeout=20) as client:
        resp = client.post(url, headers=_headers(), json={"email": email})
    data = resp.json() if resp.content else {}
    if resp.status_code >= 400:
        return AuthResult(success=False, message=data.get("msg") or "Reset request failed.", raw=data)
    return AuthResult(success=True, email=email, message="Reset OTP sent.", raw=data)


def verify_reset_otp(email: str, otp: str) -> AuthResult:
    return verify_email_otp(email, otp)


def reset_password(email: str, otp: str, new_password: str) -> AuthResult:
    email = email.strip().lower()
    if settings.AUTH_STUB_MODE or not _configured():
        expected = cache.get(_stub_otp_key(email))
        if not expected or not secrets.compare_digest(str(expected), str(otp)):
            return AuthResult(success=False, message="Invalid or expired OTP.")
        cache.delete(_stub_otp_key(email))
        cache.set(_stub_password_key(email), _hash_password(new_password), timeout=None)
        return AuthResult(success=True, email=email, message="Password updated.")

    verified = verify_email_otp(email, otp)
    if not verified.success:
        return verified

    if settings.SUPABASE_SERVICE_ROLE_KEY and verified.supabase_uid:
        url = f"{settings.SUPABASE_URL.rstrip('/')}/auth/v1/admin/users/{verified.supabase_uid}"
        with httpx.Client(timeout=20) as client:
            resp = client.put(
                url,
                headers=_headers(service=True),
                json={"password": new_password},
            )
        data = resp.json() if resp.content else {}
        if resp.status_code >= 400:
            return AuthResult(success=False, message=data.get("msg") or "Password update failed.", raw=data)
        return AuthResult(success=True, email=email, message="Password updated.", raw=data)

    return AuthResult(success=True, email=email, message="Password updated.", raw=verified.raw)
