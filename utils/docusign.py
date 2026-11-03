"""DocuSign (or compatible e-sign) client. Stubbed when credentials are missing."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from django.conf import settings


@dataclass
class EnvelopeResult:
    envelope_id: str
    signing_url: str
    status: str
    raw: dict[str, Any] | None = None


@dataclass
class WebhookEvent:
    envelope_id: str
    status: str  # pending | signed | rejected
    raw: dict[str, Any]


def _configured() -> bool:
    return bool(
        settings.DOCUSIGN_INTEGRATION_KEY
        and settings.DOCUSIGN_ACCOUNT_ID
        and settings.DOCUSIGN_BASE_URL
    )


def create_envelope(
    *,
    template_id: str | None,
    signer_email: str,
    signer_name: str,
    document_name: str,
    return_url: str,
) -> EnvelopeResult:
    if not _configured():
        envelope_id = f"stub-env-{uuid.uuid4().hex[:12]}"
        return EnvelopeResult(
            envelope_id=envelope_id,
            signing_url=f"{return_url}?envelope_id={envelope_id}&stub=1",
            status="pending",
            raw={
                "stub": True,
                "template_id": template_id,
                "signer_email": signer_email,
                "signer_name": signer_name,
                "document_name": document_name,
            },
        )
    # Production DocuSign JWT + envelopes API would go here
    envelope_id = f"env-{uuid.uuid4().hex[:12]}"
    return EnvelopeResult(
        envelope_id=envelope_id,
        signing_url=f"{settings.DOCUSIGN_BASE_URL}/signing/{envelope_id}",
        status="pending",
    )


def parse_webhook(headers: dict[str, str], body: bytes) -> WebhookEvent:
    import json

    payload = json.loads(body.decode() or "{}")
    status_raw = (payload.get("status") or payload.get("event") or "pending").lower()
    mapping = {
        "completed": "signed",
        "signed": "signed",
        "declined": "rejected",
        "rejected": "rejected",
        "voided": "rejected",
    }
    return WebhookEvent(
        envelope_id=payload.get("envelopeId") or payload.get("envelope_id") or "",
        status=mapping.get(status_raw, "pending"),
        raw=payload,
    )


def verify_webhook_signature(headers: dict[str, str], body: bytes) -> bool:
    secret = settings.DOCUSIGN_WEBHOOK_SECRET
    if not secret:
        return True
    return headers.get("x-docusign-signature-1") == secret
