from django.conf import settings
from django.db import models

from common.models import UUIDModel


class SupportTicket(UUIDModel):
    class RoleScope(models.TextChoices):
        MERCHANT = "merchant", "Merchant"
        INVESTOR = "investor", "Investor"

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        PENDING = "pending", "Pending"
        CLOSED = "closed", "Closed"

    requester = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="support_tickets",
    )
    role_scope = models.CharField(max_length=16, choices=RoleScope.choices)
    title = models.CharField(max_length=255)
    topic = models.CharField(max_length=64)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    closed_at = models.DateTimeField(null=True, blank=True)
    last_message_at = models.DateTimeField(null=True, blank=True)
    code = models.CharField(max_length=32, unique=True)

    class Meta:
        ordering = ["-last_message_at", "-created_at"]


class SupportMessage(UUIDModel):
    ticket = models.ForeignKey(SupportTicket, on_delete=models.CASCADE, related_name="messages")
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="support_messages",
    )
    body = models.TextField()

    class Meta:
        ordering = ["created_at"]
