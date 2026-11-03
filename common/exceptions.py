from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler


def api_exception_handler(exc, context):
    response = exception_handler(exc, context)
    if response is None:
        return Response(
            {"detail": "Internal server error.", "code": "server_error"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
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
    payload = {"detail": detail, "code": code}
    if fields:
        payload["fields"] = fields
    response.data = payload
    return response
