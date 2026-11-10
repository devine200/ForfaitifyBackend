from django.conf import settings
from rest_framework import serializers

from accounts.models import InvestorProfile, MerchantProfile
from kyc.models import KycRecord, ReviewStatus


class KycStatusSerializer(serializers.ModelSerializer):
    is_fully_approved = serializers.BooleanField(read_only=True)
    mode = serializers.SerializerMethodField()

    class Meta:
        model = KycRecord
        fields = (
            "verification_kind",
            "provider_session_id",
            "provider_status",
            "admin_status",
            "is_fully_approved",
            "reviewed_at",
            "liveness_status",
            "liveness_score",
            "mode",
        )

    def get_mode(self, obj):
        return settings.DIDIT_MODE


class AdminKycDecisionSerializer(serializers.Serializer):
    admin_status = serializers.ChoiceField(
        choices=[ReviewStatus.APPROVED, ReviewStatus.REJECTED]
    )


class AccountStatusSerializer(serializers.Serializer):
    account_status = serializers.ChoiceField(choices=["active", "suspended"])


class AdminMerchantSerializer(serializers.ModelSerializer):
    email = serializers.EmailField(source="user.email")
    full_name = serializers.CharField(source="user.full_name")
    kyc = serializers.SerializerMethodField()
    registered = serializers.DateTimeField(source="created_at")

    class Meta:
        model = MerchantProfile
        fields = (
            "id",
            "email",
            "full_name",
            "business_name",
            "industry",
            "years_in_operation",
            "account_status",
            "kyc",
            "registered",
        )

    def get_kyc(self, obj):
        kyc = next((row for row in obj.user.kyc_records.all() if row.verification_kind == "kyb"), None)
        if not kyc:
            return {
                "verification_kind": "kyb",
                "provider_status": "pending",
                "admin_status": "pending",
                "is_fully_approved": False,
            }
        return {
            "verification_kind": kyc.verification_kind or "kyb",
            "provider_status": kyc.provider_status,
            "admin_status": kyc.admin_status,
            "is_fully_approved": kyc.is_fully_approved,
        }


class AdminInvestorSerializer(serializers.ModelSerializer):
    email = serializers.EmailField(source="user.email")
    full_name = serializers.CharField(source="user.full_name")
    kyc = serializers.SerializerMethodField()
    registered = serializers.DateTimeField(source="created_at")

    class Meta:
        model = InvestorProfile
        fields = (
            "id",
            "email",
            "full_name",
            "account_status",
            "kyc",
            "registered",
        )

    def get_kyc(self, obj):
        kyc = next((row for row in obj.user.kyc_records.all() if row.verification_kind == "kyc"), None)
        if not kyc:
            return {
                "verification_kind": "kyc",
                "provider_status": "pending",
                "admin_status": "pending",
                "is_fully_approved": False,
            }
        return {
            "verification_kind": kyc.verification_kind or "kyc",
            "provider_status": kyc.provider_status,
            "admin_status": kyc.admin_status,
            "is_fully_approved": kyc.is_fully_approved,
        }
