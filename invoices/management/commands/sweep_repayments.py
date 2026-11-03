from django.core.management.base import BaseCommand

from invoices.tasks import sweep_auto_repayments


class Command(BaseCommand):
    help = "Mark overdue invoices and auto-repay from merchant available balances."

    def handle(self, *args, **options):
        result = sweep_auto_repayments()
        self.stdout.write(self.style.SUCCESS(str(result)))
