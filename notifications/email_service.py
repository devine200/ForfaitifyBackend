"""Branded email rendering + provider send helpers."""

from __future__ import annotations

import base64
import logging
import re
from email.mime.image import MIMEImage
from pathlib import Path

import httpx
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

from notifications.email_copy import compose

logger = logging.getLogger("forfaitify.email")


BUCKET_TEMPLATES = {
    "money": "email/money/generic.html",
    "cosign": "email/cosign/generic.html",
    "investment": "email/investment/generic.html",
}

LOGO_PATH = Path(__file__).resolve().parent / "brand" / "logo-lockup.png"
LOGO_CID = "forfaitify-logo"


def links_for_role(role_scope: str) -> tuple[str, str]:
    if role_scope == "investor":
        return "/investor/settings?tab=notifications", "/investor/support"
    if role_scope == "admin":
        return "/admin/settings", "/admin/support"
    return "/merchant/settings?tab=notifications", "/merchant/support"


def first_name(full_name: str) -> str:
    cleaned = (full_name or "").strip()
    if not cleaned:
        return ""
    return cleaned.split()[0]


def _as_facts(raw) -> list[dict]:
    facts = []
    for item in raw or []:
        if isinstance(item, dict) and item.get("label") and item.get("value"):
            facts.append({"label": item["label"], "value": item["value"]})
        elif isinstance(item, (list, tuple)) and len(item) == 2 and item[0] and item[1]:
            facts.append({"label": item[0], "value": item[1]})
    return facts


def logo_bytes() -> bytes | None:
    try:
        return LOGO_PATH.read_bytes()
    except OSError:
        return None


def absolute_href(href: str) -> str:
    base = getattr(settings, "FRONTEND_BASE_URL", "http://localhost:5173").rstrip("/")
    if not href:
        return f"{base}/"
    if href.startswith("http://") or href.startswith("https://"):
        return href
    return f"{base}{href if href.startswith('/') else '/' + href}"


def format_usd(cents: int | None) -> str:
    if cents is None:
        return "—"
    return f"${cents / 100:,.2f}"


def render_email(
    *,
    email_bucket: str,
    title: str,
    body: str,
    href: str = "",
    context: dict | None = None,
    event_type: str = "",
    recipient_name: str = "",
    role_scope: str = "merchant",
) -> tuple[str, str, str]:
    extra = dict(context or {})
    if extra.get("amount_cents") is not None:
        extra["amount_label"] = format_usd(int(extra["amount_cents"]))
    if extra.get("outstanding_cents") is not None:
        extra["outstanding_label"] = format_usd(int(extra["outstanding_cents"]))

    copy = compose(event_type, extra) or {}
    default_prefs, default_support = links_for_role(role_scope or "merchant")
    prefs_path = extra.pop("prefs_url", None) or copy.get("prefs_path") or default_prefs
    support_path = extra.pop("support_url", None) or copy.get("support_path") or default_support
    cta_label = copy.get("cta_label") or extra.pop("cta_label", None) or "View in Forfaitify"
    headline = copy.get("headline") or extra.pop("headline", None) or title
    written_body = copy.get("body") or body
    subject = (copy.get("subject") or extra.pop("subject", None) or headline or title)[:200]
    show_prefs = copy.get("show_prefs", extra.pop("show_prefs", True))
    facts = _as_facts(copy.get("facts") or extra.pop("facts", None))
    ctx = {
        "title": title,
        "headline": headline,
        "body": written_body,
        "preheader": copy.get("preheader") or extra.pop("preheader", None) or written_body[:140],
        "eyebrow": copy.get("eyebrow") or extra.pop("eyebrow", ""),
        "why": copy.get("why") or extra.pop("why", None) or "You are receiving this because of activity on your Forfaitify account.",
        "recipient_name": recipient_name or extra.pop("recipient_name", ""),
        "facts": facts,
        "show_prefs": show_prefs,
        "code": extra.pop("code", ""),
        "cta_url": absolute_href(raw_href) if (raw_href := (href or extra.pop("href", ""))) else "",
        "cta_label": cta_label,
        "prefs_url": absolute_href(prefs_path),
        "support_url": absolute_href(support_path),
        "brand_name": "Forfaitify",
    }
    template = BUCKET_TEMPLATES.get(email_bucket, "email/money/generic.html")
    html = render_to_string(template, ctx)
    text = render_to_string("email/text/generic.txt", ctx)
    return subject, html, text


def parse_from_address(raw: str) -> tuple[str, str]:
    """Split 'Name <addr@host>' into (address, name)."""
    match = re.match(r"^(?P<name>.*?)\s*<(?P<addr>[^>]+)>\s*$", raw.strip())
    if match:
        return match.group("addr").strip(), match.group("name").strip().strip('"') or "Forfaitify"
    return raw.strip(), "Forfaitify"


def _zoho_request_id(payload: object) -> str:
    if not isinstance(payload, dict):
        return ""
    request_id = payload.get("request_id")
    if isinstance(request_id, str):
        return request_id
    data = payload.get("data")
    if isinstance(data, list) and data and isinstance(data[0], dict):
        code = data[0].get("code")
        return str(code) if code else ""
    return ""


def send_via_zoho_cpaas(
    *,
    to_email: str,
    subject: str,
    html: str,
    text: str,
    client_reference: str = "",
    unsubscribe_url: str = "",
) -> str:
    api_key = getattr(settings, "ZOHO_CPAAS_API_KEY", "")
    if not api_key:
        logger.error("Zoho CPaaS send aborted: ZOHO_CPAAS_API_KEY is not set")
        raise RuntimeError("ZOHO_CPAAS_API_KEY is not set.")
    base = getattr(settings, "ZOHO_CPAAS_BASE_URL", "https://cpaas.zoho.com").rstrip("/")
    address, name = parse_from_address(
        getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@forfaitify.com")
    )
    logger.info(
        "Zoho CPaaS send start to=%s from=%s base=%s ref=%s",
        to_email,
        address,
        base,
        client_reference or "-",
    )
    body: dict = {
        "from": {"address": address, "name": name},
        "to": [{"email_address": {"address": to_email}}],
        "subject": subject,
        "htmlbody": html,
        "textbody": text,
        "track_clicks": False,
        "track_opens": False,
    }
    logo = logo_bytes()
    if logo and "cid:forfaitify-logo" in html:
        body["inline_images"] = [
            {
                "mime_type": "image/png",
                "name": "forfaitify-logo.png",
                "content": base64.b64encode(logo).decode("ascii"),
                "cid": LOGO_CID,
            }
        ]
    if unsubscribe_url:
        body["mime_headers"] = {"List-Unsubscribe": f"<{unsubscribe_url}>"}
    if client_reference:
        body["client_reference"] = client_reference[:255]

    response = httpx.post(
        f"{base}/v1.1/email",
        json=body,
        headers={
            "Authorization": f"Zoho-enczapikey {api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        timeout=20.0,
    )
    try:
        payload = response.json()
    except ValueError:
        payload = {"message": response.text[:500]}
    if response.status_code >= 400:
        message = payload.get("message") if isinstance(payload, dict) else response.text
        detail = ""
        if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
            detail = payload["data"].get("message") or payload["data"].get("error_code") or ""
        logger.error(
            "Zoho CPaaS email failed status=%s to=%s from=%s detail=%s payload=%s",
            response.status_code,
            to_email,
            address,
            detail or message,
            payload,
        )
        raise RuntimeError(
            f"Zoho CPaaS email failed ({response.status_code}): {detail or message}"
        )
    request_id = _zoho_request_id(payload)
    logger.info("Zoho CPaaS email sent to=%s zoho_request_id=%s", to_email, request_id or "-")
    return request_id


def send_multipart_email(
    *,
    to_email: str,
    subject: str,
    html: str,
    text: str,
    client_reference: str = "",
    unsubscribe_url: str = "",
) -> str:
    if getattr(settings, "EMAIL_PROVIDER", "") == "zoho_cpaas":
        return send_via_zoho_cpaas(
            to_email=to_email,
            subject=subject,
            html=html,
            text=text,
            client_reference=client_reference,
            unsubscribe_url=unsubscribe_url,
        )

    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@forfaitify.com")
    logger.info(
        "Django email send start backend=%s to=%s from=%s ref=%s",
        getattr(settings, "EMAIL_BACKEND", "-"),
        to_email,
        from_email,
        client_reference or "-",
    )
    headers = {}
    if unsubscribe_url:
        headers["List-Unsubscribe"] = f"<{unsubscribe_url}>"
    msg = EmailMultiAlternatives(
        subject=subject,
        body=text,
        from_email=from_email,
        to=[to_email],
        headers=headers,
    )
    msg.attach_alternative(html, "text/html")
    logo = logo_bytes()
    if logo and "cid:forfaitify-logo" in html:
        msg.mixed_subtype = "related"
        image = MIMEImage(logo, _subtype="png")
        image.add_header("Content-ID", f"<{LOGO_CID}>")
        image.add_header("Content-Disposition", "inline", filename="forfaitify-logo.png")
        msg.attach(image)
    try:
        msg.send(fail_silently=False)
    except Exception:
        logger.exception("Django email send failed to=%s from=%s", to_email, from_email)
        raise
    logger.info("Django email sent to=%s subject=%s", to_email, subject)
    return ""
