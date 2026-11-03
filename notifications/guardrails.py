"""Email rate limits, idempotency, and circuit breaker (cache/Redis-backed)."""

from __future__ import annotations

from django.conf import settings
from django.core.cache import cache


def _hour_key(user_key: str) -> str:
    return f"email:rate:hour:{user_key}"


def _day_key(user_key: str) -> str:
    return f"email:rate:day:{user_key}"


def _circuit_fail_key() -> str:
    return "email:circuit:failures"


def _circuit_open_key() -> str:
    return "email:circuit:open"


def circuit_is_open() -> bool:
    return bool(cache.get(_circuit_open_key()))


def record_provider_failure() -> None:
    threshold = int(getattr(settings, "EMAIL_CIRCUIT_FAILURE_THRESHOLD", 10))
    cooldown = int(getattr(settings, "EMAIL_CIRCUIT_COOLDOWN_SECONDS", 120))
    key = _circuit_fail_key()
    try:
        n = cache.incr(key)
    except ValueError:
        cache.set(key, 1, timeout=120)
        n = 1
    if n >= threshold:
        cache.set(_circuit_open_key(), 1, timeout=cooldown)


def record_provider_success() -> None:
    cache.delete(_circuit_fail_key())
    cache.delete(_circuit_open_key())


def check_user_rate_limit(user_key: str) -> bool:
    """Return True if send is allowed."""
    hour_max = int(getattr(settings, "EMAIL_RATE_PER_USER_HOUR", 10))
    day_max = int(getattr(settings, "EMAIL_RATE_PER_USER_DAY", 30))
    hk = _hour_key(user_key)
    dk = _day_key(user_key)
    hour = cache.get(hk) or 0
    day = cache.get(dk) or 0
    if hour >= hour_max or day >= day_max:
        return False
    return True


def bump_user_rate_limit(user_key: str) -> None:
    hk = _hour_key(user_key)
    dk = _day_key(user_key)
    try:
        cache.incr(hk)
    except ValueError:
        cache.set(hk, 1, timeout=3600)
    try:
        cache.incr(dk)
    except ValueError:
        cache.set(dk, 1, timeout=86400)
