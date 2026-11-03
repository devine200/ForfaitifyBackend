"""Recipient-specific copy for transactional emails."""

from __future__ import annotations


def _money(cents) -> str:
    if cents is None:
        return ""
    try:
        return f"${int(cents) / 100:,.2f}"
    except (TypeError, ValueError):
        return str(cents)


def _first(ctx: dict, *keys: str, default: str = "") -> str:
    for key in keys:
        value = ctx.get(key)
        if value:
            return str(value)
    return default


def compose(event_type: str, ctx: dict) -> dict | None:
    """Return layout fields for a known event, or None to keep the caller's title and body."""
    amount = ctx.get("amount_label") or _money(ctx.get("amount_cents"))
    invoice = _first(ctx, "invoice_code", "fact_value")
    pool = _first(ctx, "pool_name")
    outstanding = ctx.get("outstanding_label") or _money(ctx.get("outstanding_cents"))
    decision = _first(ctx, "decision").lower()
    status = _first(ctx, "status").lower()
    inviter = _first(ctx, "inviter_name", "party_name")
    state = _first(ctx, "state_label")
    epoch = _first(ctx, "epoch_index", "fact_value")

    if event_type == "payment.deposit.succeeded":
        return {
            "subject": f"Your {amount} deposit is in your balance",
            "preheader": f"{amount} is now available on Forfaitify.",
            "eyebrow": "Balance",
            "headline": "Your deposit is confirmed",
            "body": (
                f"We added {amount} to your available balance. "
                "You can keep it there, allocate it to a pool, or use it toward an invoice."
            ),
            "facts": [("Amount", amount), ("Status", "Available")],
            "cta_label": "View your balance",
            "why": "You are receiving this because money was added to your Forfaitify balance.",
        }

    if event_type == "payment.withdrawal.submitted":
        return {
            "subject": f"We received your {amount} withdrawal request",
            "preheader": "The amount is on hold while the payout is reviewed.",
            "eyebrow": "Withdrawal",
            "headline": "Your withdrawal is in review",
            "body": (
                f"We received your request to withdraw {amount}. "
                "That amount is on hold so it cannot be used elsewhere while the payout is reviewed. "
                "We will email you when it is approved or returned to your balance."
            ),
            "facts": [("Amount", amount), ("Status", "Pending review")],
            "cta_label": "View your balance",
            "why": "You are receiving this because you requested a withdrawal.",
        }

    if event_type == "payment.withdrawal.decided":
        approved = decision in ("approved", "approve") or _first(ctx, "fact_value").lower() == "approved"
        if approved:
            return {
                "subject": f"Your {amount} withdrawal was approved",
                "preheader": "The payout has been released to your selected method.",
                "eyebrow": "Withdrawal",
                "headline": "Your withdrawal was approved",
                "body": (
                    f"Your withdrawal of {amount} was approved. "
                    "The hold has been released for payout to the method you selected. "
                    "Your bank or payout provider determines when the funds arrive."
                ),
                "facts": [("Amount", amount), ("Decision", "Approved")],
                "cta_label": "View your balance",
                "why": "You are receiving this because a withdrawal on your account was decided.",
            }
        return {
            "subject": f"Your {amount} withdrawal was not approved",
            "preheader": "The held amount is back in your available balance.",
            "eyebrow": "Withdrawal",
            "headline": "Your withdrawal was returned",
            "body": (
                f"Your withdrawal of {amount} was not approved. "
                "The hold was released, and the amount is available in your balance again."
            ),
            "facts": [("Amount", amount), ("Decision", "Not approved")],
            "cta_label": "View your balance",
            "why": "You are receiving this because a withdrawal on your account was decided.",
        }

    if event_type == "invoice.funded":
        pool_sentence = f" from {pool}" if pool else ""
        return {
            "subject": f"{invoice} has been financed" if invoice else "Your invoice has been financed",
            "preheader": f"{amount} is ready in your merchant balance.",
            "eyebrow": "Invoice financing",
            "headline": "Your invoice has been financed",
            "body": (
                f"{amount}{pool_sentence} is now in your merchant balance for {invoice or 'this invoice'}. "
                "You can withdraw it when you are ready. The repayment schedule stays on the invoice."
            ),
            "facts": [pair for pair in [("Invoice", invoice), ("Amount", amount), ("Pool", pool)] if pair[1]],
            "cta_label": "Open the invoice",
            "why": "You are receiving this because an invoice on your merchant account was financed.",
        }

    if event_type == "invoice.funded.investor":
        return {
            "subject": f"{pool} deployed {amount}" if pool else f"{amount} was deployed from your pool",
            "preheader": "Capital from your pool position was matched to an invoice.",
            "eyebrow": "Pool",
            "headline": "Your pool financed an invoice",
            "body": (
                f"{amount} from your position{f' in {pool}' if pool else ''} was deployed to "
                f"{invoice or 'a verified invoice'}. "
                "Your principal stays in the pool and is repaid as the merchant pays the invoice."
            ),
            "facts": [pair for pair in [("Pool", pool), ("Invoice", invoice), ("Amount deployed", amount)] if pair[1]],
            "cta_label": "View the pool",
            "why": "You are receiving this because a pool you are invested in deployed capital.",
        }

    if event_type == "invoice.payout.withdrawn":
        return {
            "subject": f"Funding for {invoice or 'your invoice'} was sent for payout",
            "preheader": f"{amount} left your Forfaitify balance.",
            "eyebrow": "Payout",
            "headline": "Funding was sent to your payout method",
            "body": (
                f"{amount} for {invoice or 'this invoice'} has left your Forfaitify balance "
                "for the payout method on the invoice. Repayment on this invoice is now active."
            ),
            "facts": [pair for pair in [("Invoice", invoice), ("Amount", amount)] if pair[1]],
            "cta_label": "View the invoice",
            "why": "You are receiving this because financed funds were withdrawn from your balance.",
        }

    if event_type == "invoice.repaid":
        outstanding_line = f" The outstanding balance is now {outstanding}." if outstanding else ""
        return {
            "subject": f"Repayment recorded on {invoice}" if invoice else "A repayment was recorded",
            "preheader": f"{amount} was applied to your invoice.",
            "eyebrow": "Repayment",
            "headline": "Your repayment was posted",
            "body": (
                f"We applied {amount} to {invoice or 'your invoice'}.{outstanding_line} "
                "Open the invoice to confirm the remaining balance and due date."
            ),
            "facts": [pair for pair in [("Invoice", invoice), ("Amount applied", amount), ("Outstanding", outstanding)] if pair[1]],
            "cta_label": "View the invoice",
            "why": "You are receiving this because a repayment was posted on your invoice.",
        }

    if event_type == "cosign.invite.sent":
        who = inviter or "A merchant"
        return {
            "subject": f"{who} asked you to co-sign {invoice}" if invoice else f"{who} asked you to co-sign an invoice",
            "preheader": "Review the receivable before you sign.",
            "eyebrow": "Co-sign",
            "headline": "You have a document to review",
            "body": (
                f"{who} invited you to co-sign {invoice or 'a receivable'} on Forfaitify. "
                "Open the invitation, read the terms, and sign only if you agree. "
                "The invitation expires in 14 days."
            ),
            "facts": [pair for pair in [("Invoice", invoice), ("Requested by", who)] if pair[1]],
            "cta_label": "Review and sign",
            "why": "You are receiving this because someone invited you to co-sign a Forfaitify invoice.",
            "show_prefs": False,
            "support_path": "/contact",
        }

    if event_type == "cosign.status.changed":
        signed = status == "signed"
        party = inviter or "The co-signer"
        if signed:
            return {
                "subject": f"{party} signed {invoice}" if invoice else f"{party} signed your agreement",
                "preheader": "The co-sign step on your invoice is complete.",
                "eyebrow": "Co-sign",
                "headline": "The agreement was signed",
                "body": (
                    f"{party} signed the agreement for {invoice or 'your invoice'}. "
                    "You can continue the remaining financing steps from the invoice."
                ),
                "facts": [pair for pair in [("Invoice", invoice), ("Signed by", party)] if pair[1]],
                "cta_label": "Open the invoice",
                "why": "You are receiving this because a co-signer updated an invoice you own.",
            }
        return {
            "subject": f"{party} declined to sign {invoice}" if invoice else f"{party} declined the co-sign request",
            "preheader": "The invitation was not signed.",
            "eyebrow": "Co-sign",
            "headline": "The co-sign request was declined",
            "body": (
                f"{party} declined to sign {invoice or 'your invoice'}. "
                "Your invoice is unchanged. You can invite someone else if a signature is still required."
            ),
            "facts": [pair for pair in [("Invoice", invoice), ("Declined by", party)] if pair[1]],
            "cta_label": "Open the invoice",
            "why": "You are receiving this because a co-signer updated an invoice you own.",
        }

    if event_type == "pool.deposit":
        return {
            "subject": f"You added {amount} to {pool}" if pool else f"You added {amount} to a pool",
            "preheader": "The amount moved from your balance into your pool position.",
            "eyebrow": "Investment",
            "headline": "Your pool deposit is confirmed",
            "body": (
                f"{amount} moved from your available balance into your position"
                f"{f' in {pool}' if pool else ''}. "
                "That capital can be deployed when the pool matches an invoice."
            ),
            "facts": [pair for pair in [("Pool", pool), ("Amount", amount)] if pair[1]],
            "cta_label": "View the pool",
            "why": "You are receiving this because you deposited into a Forfaitify pool.",
        }

    if event_type == "pool.withdrawal.requested":
        return {
            "subject": f"Withdrawal request received for {pool}" if pool else "We received your pool withdrawal request",
            "preheader": f"{amount} stays in the pool until the request is decided.",
            "eyebrow": "Investment",
            "headline": "Your pool withdrawal is awaiting a decision",
            "body": (
                f"We recorded your request to withdraw {amount}"
                f"{f' from {pool}' if pool else ''}. "
                "The amount stays in your position until the request is accepted and settled."
            ),
            "facts": [pair for pair in [("Pool", pool), ("Amount", amount), ("Status", "Pending")] if pair[1]],
            "cta_label": "View the pool",
            "why": "You are receiving this because you requested a withdrawal from a pool.",
        }

    if event_type == "pool.withdrawal.decided":
        accepted = decision in ("accept", "accepted")
        if accepted:
            return {
                "subject": f"Your withdrawal from {pool} was accepted" if pool else "Your pool withdrawal was accepted",
                "preheader": f"{amount} will return to your balance once it is settled.",
                "eyebrow": "Investment",
                "headline": "Your pool withdrawal was accepted",
                "body": (
                    f"Your request to withdraw {amount}"
                    f"{f' from {pool}' if pool else ''} was accepted. "
                    "The amount returns to your available balance when the withdrawal is settled."
                ),
                "facts": [pair for pair in [("Pool", pool), ("Amount", amount), ("Decision", "Accepted")] if pair[1]],
                "cta_label": "View the pool",
                "why": "You are receiving this because a pool withdrawal was decided.",
            }
        return {
            "subject": f"Your withdrawal from {pool} was declined" if pool else "Your pool withdrawal was declined",
            "preheader": "Your position in the pool is unchanged.",
            "eyebrow": "Investment",
            "headline": "Your pool withdrawal was declined",
            "body": (
                f"Your request to withdraw {amount}"
                f"{f' from {pool}' if pool else ''} was declined. "
                "Your position is unchanged."
            ),
            "facts": [pair for pair in [("Pool", pool), ("Amount", amount), ("Decision", "Declined")] if pair[1]],
            "cta_label": "View the pool",
            "why": "You are receiving this because a pool withdrawal was decided.",
        }

    if event_type == "pool.withdrawal.settled":
        return {
            "subject": f"{amount} from {pool} is back in your balance" if pool else f"{amount} is back in your balance",
            "preheader": "The pool withdrawal has been settled.",
            "eyebrow": "Balance",
            "headline": "Your pool withdrawal was settled",
            "body": (
                f"{amount}"
                f"{f' from {pool}' if pool else ''} is now in your available balance. "
                "You can leave it there, move it to another pool, or withdraw it."
            ),
            "facts": [pair for pair in [("Pool", pool), ("Amount", amount), ("Status", "In your balance")] if pair[1]],
            "cta_label": "View your balance",
            "why": "You are receiving this because a pool withdrawal was paid into your balance.",
        }

    if event_type == "epoch.advanced":
        where = f" of {pool}" if pool else ""
        moved = f" is now {state}" if state else " has moved forward"
        return {
            "subject": f"{pool} is now {state}" if pool and state else "A pool epoch moved forward",
            "preheader": "Open the pool to see what changed for your position.",
            "eyebrow": "Epoch",
            "headline": "Your pool entered a new stage",
            "body": (
                f"Epoch {epoch or 'current'}{where}{moved}. "
                "This can change when deposits, withdrawals, and distributions are open. "
                "Open the pool for the current window and your position."
            ),
            "facts": [pair for pair in [("Pool", pool), ("Epoch", epoch), ("Stage", state)] if pair[1]],
            "cta_label": "View the pool",
            "why": "You are receiving this because a pool you are invested in changed epoch.",
        }

    return None
