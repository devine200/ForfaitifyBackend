from rest_framework import serializers

from admin_ops.models import AdminInvite, PaymentGatewayConfig, PlatformFees


class PlatformFeesSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlatformFees
        fields = (
            "id",
            "platform_fee_bps",
            "withdrawal_fee_bps",
            "lateness_fee_bps",
            "effective_at",
        )


class PaymentGatewaySerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentGatewayConfig
        fields = ("id", "name", "detail", "status", "is_primary", "created_at")


class AdminInviteSerializer(serializers.ModelSerializer):
    class Meta:
        model = AdminInvite
        fields = ("id", "email", "full_name", "status", "token", "created_at")
        read_only_fields = ("id", "token", "status", "created_at")


class AdminInviteCreateSerializer(serializers.Serializer):
    email = serializers.EmailField()
    full_name = serializers.CharField(required=False, allow_blank=True)


class AcceptInviteSerializer(serializers.Serializer):
    token = serializers.CharField()
    password = serializers.CharField(min_length=8)
    full_name = serializers.CharField(required=False, allow_blank=True)
