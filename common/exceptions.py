import logging

from django.conf import settings
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler

logger = logging.getLogger("forfaitify.api")


def api_exception_handler(exc, context):
    request = context.get("request")
    view = context.get("view")
    view_name = type(view).__name__ if view is not None else "-"
    path = getattr(request, "get_full_path", lambda: "-")()
    method = getattr(request, "method", "-")
    request_id = getattr(request, "request_id", "-")

    response = exception_handler(exc, context)
    if response is None:
        logger.exception(
            "Unhandled API error %s %s view=%s rid=%s: %s",
            method,
            path,
            view_name,
            request_id,
            exc,
        )
        payload = {
            "detail": "Internal server error.",
            "code": "server_error",
            "request_id": request_id,
        }
        # Surface type/message only when DEBUG so Railway/local can diagnose without logs.
        if settings.DEBUG:
            payload["error_type"] = type(exc).__name__
            payload["error"] = str(exc)
        return Response(payload, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    if response.status_code >= 500:
        logger.exception(
            "API error %s %s view=%s status=%s rid=%s: %s",
            method,
            path,
            view_name,
            response.status_code,
            request_id,
            exc,
        )
    elif response.status_code >= 400:
        logger.warning(
            "API client error %s %s view=%s status=%s rid=%s: %s",
            method,
            path,
            view_name,
            response.status_code,
            request_id,
            exc,
        )

    data = response.data
    detail = data
    fields = None
    if isinstance(data, dict):
        detail = data.get("detail", data)
        if "detail" in data and len(data) == 1:
            fields = None
        elif "detail" not in data:
            fields = data
            detail = "Validation error."
        else:
            fields = {k: v for k, v in data.items() if k != "detail"} or None

    code = getattr(exc, "default_code", None) or "error"
    payload = {"detail": detail, "code": code, "request_id": request_id}
    if fields:
        payload["fields"] = fields
    response.data = payload
    return response
