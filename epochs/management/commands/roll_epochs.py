from django.core.management.base import BaseCommand
from django.utils import timezone

from epochs.events import emit_epoch_advanced
from epochs.models import Epoch
from pools.services import ensure_current_epoch


class Command(BaseCommand):
    help = "Advance epochs past ends_at and open the next epoch when closed."

    def handle(self, *args, **options):
        now = timezone.now()
        advanced = 0
        for epoch in Epoch.objects.exclude(state=Epoch.State.CLOSED).filter(ends_at__lte=now):
            if epoch.state == Epoch.State.FUNDING_OPEN:
                epoch.state = Epoch.State.CAPITAL_DEPLOYED
            elif epoch.state == Epoch.State.CAPITAL_DEPLOYED:
                epoch.state = Epoch.State.MATURED
            elif epoch.state == Epoch.State.MATURED:
                epoch.state = Epoch.State.RETURNS_DISTRIBUTED
            elif epoch.state == Epoch.State.RETURNS_DISTRIBUTED:
                epoch.state = Epoch.State.CLOSED
                ensure_current_epoch(epoch.pool)
            epoch.save(update_fields=["state", "updated_at"])
            emit_epoch_advanced(epoch)
            advanced += 1
        self.stdout.write(self.style.SUCCESS(f"Advanced {advanced} epoch(s)."))
