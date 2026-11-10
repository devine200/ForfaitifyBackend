"""Helpers for current PlatformFees configuration."""

from admin_ops.models import PlatformFees


def current_fees() -> PlatformFees:
    fees = PlatformFees.objects.order_by("-effective_at").first()
    if not fees:
        fees = PlatformFees.objects.create()
    return fees


def bps_of(amount_cents: int, bps: int) -> int:
    if amount_cents <= 0 or bps <= 0:
        return 0
    return (amount_cents * bps) // 10_000
