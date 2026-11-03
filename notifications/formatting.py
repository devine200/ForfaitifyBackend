def format_usd(cents: int | None) -> str:
    """Format minor units (kobo) as NGN. Name kept for call-site compatibility."""
    if cents is None:
        return "—"
    return f"₦{cents / 100:,.2f}"


def format_ngn(cents: int | None) -> str:
    return format_usd(cents)
