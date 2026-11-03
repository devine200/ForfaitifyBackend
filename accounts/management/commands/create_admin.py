from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from balances.services import get_or_create_balance
from kyc.models import KycRecord, ReviewStatus

User = get_user_model()


class Command(BaseCommand):
    help = "Create or promote a flat admin user."

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True)
        parser.add_argument("--password", required=True)
        parser.add_argument("--name", default="Admin")

    def handle(self, *args, **options):
        email = options["email"].strip().lower()
        user, created = User.objects.get_or_create(
            email=email,
            defaults={
                "full_name": options["name"],
                "is_active": True,
                "is_staff": True,
                "is_admin": True,
                "email_verified": True,
            },
        )
        user.set_password(options["password"])
        user.is_active = True
        user.is_staff = True
        user.is_admin = True
        user.email_verified = True
        user.full_name = options["name"]
        user.save()
        KycRecord.objects.get_or_create(
            user=user,
            verification_kind="",
            defaults={
                "provider_status": ReviewStatus.APPROVED,
                "admin_status": ReviewStatus.APPROVED,
            },
        )
        get_or_create_balance(user)
        action = "Created" if created else "Updated"
        self.stdout.write(self.style.SUCCESS(f"{action} admin {email}"))
