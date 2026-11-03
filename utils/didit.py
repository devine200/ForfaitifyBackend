"""Didit KYC/KYB client. Documents stay on Didit; we only keep session id and status."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from dataclasses import dataclass
from typing import Any

import httpx
from django.conf import settings

SESSION_URL = "https://verification.didit.me/v3/session/"


@dataclass
class DiditSession:
    session_id: str
    url: str
    status: str  # pending | processing | approved | rejected


@dataclass
class WebhookEvent:
    session_id: str
    vendor_data: str
    review_status: str
    raw: dict[str, Any]


# Didit status strings are case-sensitive.
_STATUS = {
    "Approved": "approved",
    "Declined": "rejected",
    "In Review": "processing",
    "In Progress": "processing",
    "Awaiting User": "processing",
    "Resubmitted": "processing",
    "Not Started": "pending",
    "Abandoned": "pending",
    "Expired": "rejected",
    "Kyc Expired": "rejected",
}


def map_status(raw: str | None) -> str:
    text = (raw or "").strip()
    if text in _STATUS:
        return _STATUS[text]
    value = text.upper().replace(" ", "_").replace("-", "_")
    if value == "APPROVED":
        return "approved"
    if value in {"DECLINED", "REJECTED", "EXPIRED", "KYC_EXPIRED"}:
        return "rejected"
    if value in {"NOT_STARTED", "ABANDONED", ""}:
        return "pending"
    return "processing"


def _configured() -> bool:
    return bool(settings.DIDIT_API_KEY)


def create_session(*, user_id: str, workflow_id: str, callback_url: str) -> DiditSession:
    if settings.DIDIT_MODE == "live" and not _configured():
        raise RuntimeError("Didit live mode is on, but DIDIT_API_KEY is empty.")
    if not _configured():
        session_id = f"stub-{user_id[:16]}-{uuid.uuid4().hex[:8]}"
        return DiditSession(
            session_id=session_id,
            url=f"{callback_url}?verificationSessionId={session_id}&status=In%20Review",
            status="processing",
        )
    if not workflow_id:
        label = "live" if settings.DIDIT_MODE == "live" else "test"
        raise RuntimeError(f"Didit {label} workflow id is not configured.")

    payload = {
        "workflow_id": workflow_id,
        "vendor_data": user_id,
        "callback": callback_url,
        "callback_method": "both",
    }
    if settings.DIDIT_MODE == "test" and settings.DIDIT_SANDBOX_SCENARIO:
        payload["sandbox_scenario"] = settings.DIDIT_SANDBOX_SCENARIO
    with httpx.Client(timeout=20) as client:
        resp = client.post(
            SESSION_URL,
            headers={
                "x-api-key": settings.DIDIT_API_KEY,
                "Content-Type": "application/json",
            },
            json=payload,
        )
    data = resp.json() if resp.content else {}
    if resp.status_code >= 400:
        detail = data.get("detail") or data.get("message") or resp.text or "Didit session failed."
        raise RuntimeError(str(detail))
    session_id = str(data.get("session_id") or "")
    url = str(data.get("url") or "")
    if not session_id or not url:
        raise RuntimeError("Didit did not return a verification url.")
    return DiditSession(session_id=session_id, url=url, status=map_status(data.get("status")))


def slim_webhook(payload: dict[str, Any]) -> dict[str, Any]:
    """Status metadata only. Decision documents and media stay on Didit."""
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    return {
        "event_id": payload.get("event_id"),
        "webhook_type": payload.get("webhook_type") or payload.get("event"),
        "timestamp": payload.get("timestamp"),
        "session_id": payload.get("session_id") or data.get("session_id"),
        "vendor_data": payload.get("vendor_data") or data.get("vendor_data"),
        "status": payload.get("status") or data.get("status"),
        "session_kind": payload.get("session_kind") or data.get("session_kind"),
    }


def parse_webhook(body: bytes) -> WebhookEvent:
    payload = json.loads(body.decode() or "{}")
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    session_id = str(payload.get("session_id") or data.get("session_id") or "")
    vendor_data = str(payload.get("vendor_data") or data.get("vendor_data") or "")
    status = map_status(payload.get("status") or data.get("status"))
    return WebhookEvent(
        session_id=session_id,
        vendor_data=vendor_data,
        review_status=status,
        raw=slim_webhook(payload),
    )


def _header(headers: dict[str, str], name: str) -> str:
    wanted = name.lower()
    for key, value in headers.items():
        if key.lower() == wanted and value:
            return value
    return ""


def _shorten_floats(value: Any) -> Any:
    if isinstance(value, list):
        return [_shorten_floats(item) for item in value]
    if isinstance(value, dict):
        return {key: _shorten_floats(item) for key, item in value.items()}
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def canonical_json(payload: Any) -> str:
    """shortenFloats → recursive key sort → compact JSON with unescaped Unicode."""
    return json.dumps(
        _shorten_floats(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def verify_webhook_signature(headers: dict[str, str], body: bytes) -> bool:
    """Verify X-Signature-V2. Freshness uses the signed body timestamp, not X-Timestamp."""
    secret = settings.DIDIT_WEBHOOK_SECRET
    if not secret:
        return False
    sig = _header(headers, "X-Signature-V2")
    if not sig:
        return False
    try:
        payload = json.loads(body.decode() or "{}")
    except json.JSONDecodeError:
        return False
    expected = hmac.new(secret.encode(), canonical_json(payload).encode(), hashlib.sha256).hexdigest()
    if len(sig) != len(expected) or not hmac.compare_digest(expected, sig):
        return False
    try:
        ts = float(payload.get("timestamp"))
    except (TypeError, ValueError):
        return False
    return abs(time.time() - ts) <= 300
