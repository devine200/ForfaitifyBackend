from rest_framework import serializers

from payments.models import PaymentIntent, PayoutMethod


class PayoutMethodSerializer(serializers.ModelSerializer):
    class Meta:
        model = PayoutMethod
        fields = (
            "id",
            "label",
            "account_ref",
            "bank_code",
            "account_name",
            "is_default",
            "created_at",
        )
        read_only_fields = ("id", "created_at")


class PaymentIntentSerializer(serializers.ModelSerializer):
    checkout_url = serializers.SerializerMethodField()

    class Meta:
        model = PaymentIntent
        fields = (
            "id",
            "kind",
            "amount_cents",
            "currency",
            "status",
            "processor",
            "processor_ref",
            "payout_method",
            "invoice",
            "requires_admin_review",
            "admin_decision",
            "settled_at",
            "created_at",
            "checkout_url",
        )

    def get_checkout_url(self, obj: PaymentIntent) -> str:
        meta = obj.meta if isinstance(obj.meta, dict) else {}
        return str(meta.get("checkout_url") or "")


class DepositSerializer(serializers.Serializer):
    amount_cents = serializers.IntegerField(min_value=1, max_value=500_000_000_00)
    idempotency_key = serializers.CharField(required=False, allow_blank=True)
    role = serializers.ChoiceField(choices=["merchant", "investor"], required=False)


class WithdrawalSerializer(serializers.Serializer):
    amount_cents = serializers.IntegerField(min_value=1, max_value=500_000_000_00)
    payout_method_id = serializers.UUIDField()
    idempotency_key = serializers.CharField(required=False, allow_blank=True)
    role = serializers.ChoiceField(choices=["merchant", "investor"], required=False)


class LedgerDecideSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(choices=["approve", "reject"])
