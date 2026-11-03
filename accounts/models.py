import uuid

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models

from common.models import TimeStampedModel, UUIDModel


class AccountStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    SUSPENDED = "suspended", "Suspended"


class DeviceKind(models.TextChoices):
    LAPTOP = "laptop", "Laptop"
    PHONE = "phone", "Phone"
    OTHER = "other", "Other"


class UserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra):
        if not email:
            raise ValueError("Email is required")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra)
        user.set_password(password or uuid.uuid4().hex)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra):
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        extra.setdefault("is_admin", True)
        extra.setdefault("is_active", True)
        return self.create_user(email, password, **extra)


class User(AbstractBaseUser, PermissionsMixin, TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True)
    supabase_uid = models.CharField(max_length=128, unique=True, null=True, blank=True)
    full_name = models.CharField(max_length=255, blank=True)
    phone = models.CharField(max_length=64, blank=True)
    country = models.CharField(max_length=128, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    avatar_url = models.URLField(blank=True)
    is_active = models.BooleanField(default=False)
    is_staff = models.BooleanField(default=False)
    is_admin = models.BooleanField(default=False)
    account_status = models.CharField(
        max_length=16,
        choices=AccountStatus.choices,
        default=AccountStatus.ACTIVE,
    )
    email_verified = models.BooleanField(default=False)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.email

    @property
    def has_merchant(self) -> bool:
        return hasattr(self, "merchant_profile")

    @property
    def has_investor(self) -> bool:
        return hasattr(self, "investor_profile")


class MerchantProfile(UUIDModel):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="merchant_profile")
    business_name = models.CharField(max_length=255, blank=True)
    industry = models.CharField(max_length=128, blank=True)
    years_in_operation = models.PositiveIntegerField(default=0)
    account_status = models.CharField(
        max_length=16,
        choices=AccountStatus.choices,
        default=AccountStatus.ACTIVE,
    )

    def __str__(self):
        return self.business_name or f"Merchant<{self.user.email}>"


class InvestorProfile(UUIDModel):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="investor_profile")
    account_status = models.CharField(
        max_length=16,
        choices=AccountStatus.choices,
        default=AccountStatus.ACTIVE,
    )
    agreement_accepted_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Investor<{self.user.email}>"


class EmailOtp(UUIDModel):
    class Purpose(models.TextChoices):
        SIGNUP = "signup", "Signup"
        PASSWORD_RESET = "password_reset", "Password reset"

    email = models.EmailField(db_index=True)
    purpose = models.CharField(max_length=32, choices=Purpose.choices)
    code_hash = models.CharField(max_length=64)
    expires_at = models.DateTimeField()
    attempts = models.PositiveSmallIntegerField(default=0)
    consumed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["email", "purpose", "consumed_at"]),
        ]


class UserSession(UUIDModel):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="sessions")
    jti = models.CharField(max_length=255, blank=True, db_index=True)
    device_label = models.CharField(max_length=255, blank=True)
    kind = models.CharField(max_length=16, choices=DeviceKind.choices, default=DeviceKind.OTHER)
    ip = models.GenericIPAddressField(null=True, blank=True)
    location_label = models.CharField(max_length=255, blank=True)
    last_seen_at = models.DateTimeField(auto_now=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-last_seen_at"]


class NotificationPreference(UUIDModel):
    class RoleScope(models.TextChoices):
        MERCHANT = "merchant", "Merchant"
        INVESTOR = "investor", "Investor"

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="notification_preferences")
    role_scope = models.CharField(max_length=16, choices=RoleScope.choices)
    category = models.CharField(max_length=64)
    enabled = models.BooleanField(default=True)

    class Meta:
        unique_together = ("user", "role_scope", "category")
