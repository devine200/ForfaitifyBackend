from rest_framework import serializers

from balances.models import Balance, BalanceTransaction


class BalanceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Balance
        fields = ("id", "currency", "available_cents", "held_cents", "updated_at")


class BalanceTransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = BalanceTransaction
        fields = (
            "id",
            "type",
            "status",
            "amount_cents",
            "destination_label",
            "invoice",
            "pool",
            "payment_intent",
            "created_at",
        )
