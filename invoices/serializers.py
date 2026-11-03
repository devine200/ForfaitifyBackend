from rest_framework import serializers

from invoices.models import Invoice, InvoiceAcknowledgement, InvoiceDocument


class InvoiceDocumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = InvoiceDocument
        fields = ("id", "name", "file", "visibility", "created_at")


class InvoiceSerializer(serializers.ModelSerializer):
    documents = InvoiceDocumentSerializer(many=True, read_only=True)
    cosigners = serializers.SerializerMethodField()

    class Meta:
        model = Invoice
        fields = (
            "id",
            "code",
            "name",
            "title",
            "merchant",
            "buyer_name",
            "industry",
            "country",
            "years_in_operation_snapshot",
            "total_amount_cents",
            "loan_amount_cents",
            "duration_days",
            "due_date",
            "apr_bps",
            "risk_tier",
            "pool",
            "review_status",
            "insurance_status",
            "finance_step",
            "payout_status",
            "repayment_state",
            "display_status",
            "repayment_amount_cents",
            "outstanding_cents",
            "funded_amount_cents",
            "amount_left_cents",
            "funding_closes_at",
            "funded_at",
            "inactive",
            "documents",
            "cosigners",
            "created_at",
            "updated_at",
        )

    def get_cosigners(self, obj):
        return [
            {
                "id": str(c.id),
                "party_name": c.party_name,
                "status": c.status,
                "signed_at": c.signed_at,
            }
            for c in obj.cosigners.all()
        ]


class InvoiceCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255)
    title = serializers.CharField(required=False, allow_blank=True)
    buyer_name = serializers.CharField(required=False, allow_blank=True)
    industry = serializers.CharField(required=False, allow_blank=True)
    country = serializers.CharField(required=False, allow_blank=True)
    years_in_operation = serializers.IntegerField(required=False, min_value=0)
    loan_amount_cents = serializers.IntegerField(min_value=1)
    total_amount_cents = serializers.IntegerField(required=False, min_value=1)
    duration_days = serializers.IntegerField(min_value=1)
    ack_repayment_terms = serializers.BooleanField()
    ack_late_penalties = serializers.BooleanField()
    ack_contract_enforcement = serializers.BooleanField()


class ReviewSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(choices=["approve", "reject"])


class InsuranceSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=["pending", "verified", "rejected"])


class FundSerializer(serializers.Serializer):
    pool_id = serializers.UUIDField()


class RepaySerializer(serializers.Serializer):
    amount_cents = serializers.IntegerField(min_value=1)


class WithdrawFundingSerializer(serializers.Serializer):
    payout_method_id = serializers.UUIDField()
