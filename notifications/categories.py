"""Shared notification category constants (camelCase; match frontend)."""

MERCHANT = {
    "invoiceUpdates",
    "deposits",
    "financingOffers",
    "securityAlerts",
}

INVESTOR = {
    "epochEvents",
    "deposits",
    "poolMatching",
    "securityAlerts",
}

ADMIN = {
    "operations",
    "securityAlerts",
}

ALWAYS_ON = {"securityAlerts"}

EMAIL_BUCKETS = frozenset({"money", "cosign", "investment"})
