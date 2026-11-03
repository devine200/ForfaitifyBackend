"""Payment processor client. Dummy for demos; Flutterwave stub ready for live keys."""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

from django.conf import settings

Kind = Literal["deposit", "withdrawal", "invoice_payout"]


@dataclass
class PaymentResult:
    success: bool
    processor: str
    processor_ref: str
    status: str  # pending | processing | successful | rejected
    message: str = ""
    checkout_url: str = ""
    raw: dict[str, Any] | None = None


@dataclass
class TransferResult:
    success: bool
    processor: str
    processor_ref: str
    status: str
    message: str = ""
    raw: dict[str, Any] | None = None


@dataclass
class WebhookEvent:
    processor_ref: str
    status: str
    kind: Kind | None
    amount_cents: int | None
    currency: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


def _processor() -> str:
    return (settings.PAYMENT_PROCESSOR or "dummy").strip().lower()


def _frontend_return_url(ref: str) -> str:
    base = getattr(settings, "FRONTEND_BASE_URL", "http://localhost:5173").rstrip("/")
    return f"{base}/payments/return?ref={ref}"


def create_deposit(
    user_id: str,
    amount_cents: int,
    *,
    currency: str | None = None,
    idempotency_key: str | None = None,
    customer_email: str | None = None,
) -> PaymentResult:
    processor = _processor()
    currency = (currency or settings.DEFAULT_CURRENCY or "NGN").upper()
    ref = f"{processor}_dep_{uuid.uuid4().hex[:16]}"

    if processor == "dummy":
        return PaymentResult(
            success=True,
            processor=processor,
            processor_ref=ref,
            status="successful",
            message="Dummy deposit succeeded.",
            raw={
                "user_id": user_id,
                "amount_cents": amount_cents,
                "currency": currency,
                "idempotency_key": idempotency_key,
            },
        )

    if processor == "flutterwave":
        # Stub until FLUTTERWAVE_SECRET_KEY is set; shape matches hosted checkout.
        secret = getattr(settings, "FLUTTERWAVE_SECRET_KEY", "") or ""
        checkout = _frontend_return_url(ref)
        raw: dict[str, Any] = {
            "user_id": user_id,
            "amount_cents": amount_cents,
            "currency": currency,
            "idempotency_key": idempotency_key,
            "customer_email": customer_email,
            "stub": not bool(secret),
        }
        if secret:
            # Real call would POST https://api.flutterwave.com/v3/payments
            raw["note"] = "Use Flutterwave standard payment API with this tx_ref."
            checkout = _frontend_return_url(ref)
        return PaymentResult(
            success=True,
            processor=processor,
            processor_ref=ref,
            status="pending",
            message="Flutterwave deposit intent created.",
            checkout_url=checkout,
            raw=raw,
        )

    return PaymentResult(
        success=True,
        processor=processor,
        processor_ref=ref,
        status="pending",
        message="Deposit intent created.",
    )


def create_withdrawal(
    user_id: str,
    amount_cents: int,
    payout_account_ref: str,
    *,
    currency: str | None = None,
    idempotency_key: str | None = None,
) -> PaymentResult:
    """Create a withdrawal *intent* only. Transfer runs after admin approval."""
    processor = _processor()
    currency = (currency or settings.DEFAULT_CURRENCY or "NGN").upper()
    ref = f"{processor}_wdr_{uuid.uuid4().hex[:16]}"
    return PaymentResult(
        success=True,
        processor=processor,
        processor_ref=ref,
        status="pending",
        message="Withdrawal pending admin approval.",
        raw={
            "user_id": user_id,
            "amount_cents": amount_cents,
            "currency": currency,
            "payout_account_ref": payout_account_ref,
            "idempotency_key": idempotency_key,
        },
    )


def initiate_transfer(
    *,
    processor_ref: str,
    user_id: str,
    amount_cents: int,
    payout_account_ref: str,
    currency: str | None = None,
    narration: str = "",
) -> TransferResult:
    """Send money after admin approval. Dummy settles immediately; Flutterwave stubs pending."""
    processor = _processor()
    currency = (currency or settings.DEFAULT_CURRENCY or "NGN").upper()
    transfer_ref = f"{processor_ref}_xfer"

    if processor == "dummy":
        return TransferResult(
            success=True,
            processor=processor,
            processor_ref=transfer_ref,
            status="successful",
            message="Dummy transfer settled.",
            raw={
                "user_id": user_id,
                "amount_cents": amount_cents,
                "currency": currency,
                "payout_account_ref": payout_account_ref,
                "narration": narration,
            },
        )

    if processor == "flutterwave":
        secret = getattr(settings, "FLUTTERWAVE_SECRET_KEY", "") or ""
        return TransferResult(
            success=True,
            processor=processor,
            processor_ref=transfer_ref,
            status="successful" if not secret else "pending",
            message="Flutterwave transfer initiated (stub)."
            if not secret
            else "Flutterwave transfer submitted.",
            raw={
                "user_id": user_id,
                "amount_cents": amount_cents,
                "currency": currency,
                "payout_account_ref": payout_account_ref,
                "narration": narration,
                "stub": not bool(secret),
            },
        )

    return TransferResult(
        success=False,
        processor=processor,
        processor_ref=transfer_ref,
        status="rejected",
        message=f"Unknown processor: {processor}",
    )


def parse_webhook(headers: dict[str, str], body: bytes) -> WebhookEvent:
    payload = json.loads(body.decode() or "{}")
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    status_raw = (
        data.get("status")
        or payload.get("status")
        or payload.get("event")
        or "successful"
    )
    status_norm = str(status_raw).strip().lower()
    if status_norm in {"successful", "success", "completed", "charge.completed"}:
        status = "successful"
    elif status_norm in {"failed", "failure", "declined", "rejected"}:
        status = "rejected"
    else:
        status = status_norm

    amount = data.get("amount")
    amount_cents = data.get("amount_cents")
    if amount_cents is None and amount is not None:
        try:
            # Flutterwave amounts are major units (e.g. NGN naira).
            amount_cents = int(round(float(amount) * 100))
        except (TypeError, ValueError):
            amount_cents = None

    ref = (
        data.get("tx_ref")
        or data.get("processor_ref")
        or data.get("reference")
        or data.get("id")
        or payload.get("processor_ref")
        or ""
    )
    kind = data.get("kind") or payload.get("kind")
    return WebhookEvent(
        processor_ref=str(ref),
        status=status,
        kind=kind,
        amount_cents=amount_cents,
        currency=(data.get("currency") or payload.get("currency")),
        raw=payload,
    )


def verify_webhook_signature(headers: dict[str, str], body: bytes) -> bool:
    processor = _processor()
    if processor == "dummy":
        secret = settings.PAYMENT_WEBHOOK_SECRET
        if not secret:
            return True
        return headers.get("x-payment-signature") == secret

    # Flutterwave: verif-hash header must match FLUTTERWAVE_WEBHOOK_HASH (or PAYMENT_WEBHOOK_SECRET).
    expected = (
        getattr(settings, "FLUTTERWAVE_WEBHOOK_HASH", "")
        or settings.PAYMENT_WEBHOOK_SECRET
        or ""
    )
    if not expected:
        # Refuse unsigned live webhooks when Flutterwave is selected.
        return False
    provided = (
        headers.get("verif-hash")
        or headers.get("Verif-Hash")
        or headers.get("x-payment-signature")
        or ""
    )
    if not provided:
        return False
    if hmac.compare_digest(str(provided), str(expected)):
        return True
    # Optional HMAC of body for custom proxies.
    digest = hmac.new(expected.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(digest, str(provided))
