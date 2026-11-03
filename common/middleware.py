"""Request logging for Railway / container stdout."""

from __future__ import annotations

import logging
import time
import uuid

logger = logging.getLogger("forfaitify.request")


class RequestLoggingMiddleware:
    """Attach a request id and log method/path/status/duration."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request_id = (
            request.headers.get("X-Request-ID")
            or request.headers.get("X-Railway-Request-Id")
            or uuid.uuid4().hex[:16]
        )
        request.request_id = request_id
        started = time.perf_counter()
        response = self.get_response(request)
        duration_ms = (time.perf_counter() - started) * 1000
        response["X-Request-ID"] = request_id

        user = getattr(request, "user", None)
        user_label = "-"
        if user is not None and getattr(user, "is_authenticated", False):
            user_label = getattr(user, "email", None) or str(getattr(user, "pk", "-"))

        level = logging.WARNING if response.status_code >= 500 else logging.INFO
        logger.log(
            level,
            "%s %s -> %s %.1fms rid=%s user=%s",
            request.method,
            request.get_full_path(),
            response.status_code,
            duration_ms,
            request_id,
            user_label,
        )
        return response
