from datetime import date

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import serializers
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import (
    InvestorProfile,
    MerchantProfile,
    NotificationPreference,
    UserSession,
)
from balances.services import get_or_create_balance
from kyc.models import KycRecord

User = get_user_model()


def is_at_least_18(born: date, today: date | None = None) -> bool:
    today = today or timezone.localdate()
    years = today.year - born.year
    if (today.month, today.day) < (born.month, born.day):
        years -= 1
    return years >= 18


class RegisterSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, min_length=8)
    full_name = serializers.CharField(max_length=255)
    country = serializers.CharField(max_length=128)
    phone = serializers.CharField(max_length=64)
    date_of_birth = serializers.DateField()
    role = serializers.ChoiceField(choices=["merchant", "investor"])
    business_name = serializers.CharField(max_length=255, required=False, allow_blank=True)

    def validate_date_of_birth(self, value: date):
        if value > timezone.localdate():
            raise serializers.ValidationError("Date of birth cannot be in the future.")
        if not is_at_least_18(value):
            raise serializers.ValidationError("You must be at least 18 years old.")
        return value

    def validate(self, attrs):
        if attrs.get("role") == "merchant":
            name = (attrs.get("business_name") or "").strip()
            if not name:
                raise serializers.ValidationError(
                    {"business_name": "Business name is required for merchant accounts."}
                )
            attrs["business_name"] = name
        else:
            attrs.pop("business_name", None)
        return attrs


class EmailOtpSerializer(serializers.Serializer):
    email = serializers.EmailField()
    otp = serializers.CharField(max_length=12)


class EmailSerializer(serializers.Serializer):
    email = serializers.EmailField()


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)
    role = serializers.ChoiceField(choices=["merchant", "investor", "admin"])


class ResetPasswordSerializer(serializers.Serializer):
    email = serializers.EmailField()
    otp = serializers.CharField(max_length=12)
    new_password = serializers.CharField(write_only=True, min_length=8)


class ProfileUpdateSerializer(serializers.Serializer):
    full_name = serializers.CharField(required=False, allow_blank=True)
    phone = serializers.CharField(required=False, allow_blank=True)
    country = serializers.CharField(required=False, allow_blank=True)
    avatar_url = serializers.URLField(required=False, allow_blank=True)
    business_name = serializers.CharField(required=False, allow_blank=True)
    industry = serializers.CharField(required=False, allow_blank=True)
    years_in_operation = serializers.IntegerField(required=False, min_value=0)


class UserSessionSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserSession
        fields = (
            "id",
            "device_label",
            "kind",
            "ip",
            "location_label",
            "last_seen_at",
            "revoked_at",
        )


class NotificationPreferenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = NotificationPreference
        fields = ("id", "role_scope", "category", "enabled")


class MeSerializer(serializers.ModelSerializer):
    has_merchant = serializers.BooleanField(read_only=True)
    has_investor = serializers.BooleanField(read_only=True)
    kyc = serializers.SerializerMethodField()
    merchant_profile = serializers.SerializerMethodField()
    investor_profile = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            "id",
            "email",
            "full_name",
            "phone",
            "country",
            "date_of_birth",
            "avatar_url",
            "is_admin",
            "account_status",
            "email_verified",
            "has_merchant",
            "has_investor",
            "kyc",
            "merchant_profile",
            "investor_profile",
            "created_at",
        )

    def get_kyc(self, obj):
        kyc = obj.kyc_records.exclude(verification_kind="").order_by("-updated_at").first()
        if not kyc:
            return {
                "verification_kind": "",
                "provider_status": "pending",
                "admin_status": "pending",
                "is_fully_approved": False,
            }
        return {
            "verification_kind": kyc.verification_kind,
            "provider_status": kyc.provider_status,
            "admin_status": kyc.admin_status,
            "is_fully_approved": kyc.is_fully_approved,
        }

    def get_merchant_profile(self, obj):
        if not hasattr(obj, "merchant_profile"):
            return None
        p = obj.merchant_profile
        return {
            "id": str(p.id),
            "business_name": p.business_name,
            "industry": p.industry,
            "years_in_operation": p.years_in_operation,
            "account_status": p.account_status,
        }

    def get_investor_profile(self, obj):
        if not hasattr(obj, "investor_profile"):
            return None
        p = obj.investor_profile
        return {
            "id": str(p.id),
            "account_status": p.account_status,
            "agreement_accepted_at": p.agreement_accepted_at,
        }


def issue_tokens_for(user: User) -> dict:
    refresh = RefreshToken.for_user(user)
    refresh["is_admin"] = user.is_admin
    refresh["has_merchant"] = user.has_merchant
    refresh["has_investor"] = user.has_investor
    return {
        "refresh": str(refresh),
        "access": str(refresh.access_token),
        "user": MeSerializer(user).data,
    }


def ensure_profile(user: User, role: str, *, business_name: str | None = None):
    if role == "merchant":
        profile, _ = MerchantProfile.objects.get_or_create(user=user)
        if business_name:
            profile.business_name = business_name
            profile.save(update_fields=["business_name", "updated_at"])
    elif role == "investor":
        InvestorProfile.objects.get_or_create(user=user)
    KycRecord.objects.get_or_create(user=user, verification_kind="")
    get_or_create_balance(user)
