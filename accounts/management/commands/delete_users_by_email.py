from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounts.models import EmailOtp

User = get_user_model()


class Command(BaseCommand):
    help = "Delete every account with one email address, plus leftover signup codes for that address."

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True)

    def handle(self, *args, **options):
        email = options["email"].strip().lower()
        if not email or "@" not in email:
            raise CommandError("Pass a full email address.")

        users = list(User.objects.filter(email__iexact=email))
        if not users:
            self.stdout.write(f"No account found for {email}.")
        else:
            with transaction.atomic():
                for user in users:
                    self.stdout.write(f"Deleting {user.email} ({user.id})")
                    user.delete()

        codes = EmailOtp.objects.filter(email__iexact=email)
        code_count = codes.count()
        if code_count:
            codes.delete()
            self.stdout.write(f"Deleted {code_count} verification code(s) for {email}.")

        self.stdout.write(self.style.SUCCESS(f"Finished. Removed {len(users)} account(s)."))
