from django.db import models

from common.models import UUIDModel


class Epoch(UUIDModel):
    class State(models.TextChoices):
        FUNDING_OPEN = "funding_open", "Funding open"
        CAPITAL_DEPLOYED = "capital_deployed", "Capital deployed"
        MATURED = "matured", "Matured"
        RETURNS_DISTRIBUTED = "returns_distributed", "Returns distributed"
        CLOSED = "closed", "Closed"

    pool = models.ForeignKey("pools.Pool", on_delete=models.CASCADE, related_name="epochs")
    index = models.PositiveIntegerField()
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    withdrawal_window_start = models.DateTimeField(null=True, blank=True)
    withdrawal_window_end = models.DateTimeField(null=True, blank=True)
    state = models.CharField(max_length=32, choices=State.choices, default=State.FUNDING_OPEN)

    class Meta:
        unique_together = ("pool", "index")
        ordering = ["-index"]

    def __str__(self):
        return f"Epoch {self.index} · {self.pool_id}"


class EpochDistribution(UUIDModel):
    epoch = models.ForeignKey(Epoch, on_delete=models.CASCADE, related_name="distributions")
    position = models.ForeignKey(
        "pools.PoolPosition",
        on_delete=models.CASCADE,
        related_name="distributions",
    )
    return_cents = models.BigIntegerField(default=0)
    posted_to_balance = models.BooleanField(default=False)

    class Meta:
        unique_together = ("epoch", "position")
