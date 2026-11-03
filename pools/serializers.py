from django.db.models import Sum
from rest_framework import serializers

from pools.models import Pool, PoolLoanTier, PoolPosition, PoolWithdrawalRequest


class PoolLoanTierSerializer(serializers.ModelSerializer):
    class Meta:
        model = PoolLoanTier
        fields = (
            "id",
            "name",
            "duration_days",
            "interest_bps",
            "invoice_min_cents",
            "invoice_max_cents",
        )


class PoolSerializer(serializers.ModelSerializer):
    loan_tiers = PoolLoanTierSerializer(many=True, read_only=True)
    current_epoch = serializers.SerializerMethodField()
    my_principal_cents = serializers.SerializerMethodField()
    total_principal_cents = serializers.SerializerMethodField()
    deployed_cents = serializers.SerializerMethodField()
    available_liquidity_cents = serializers.SerializerMethodField()
    utilization_pct = serializers.SerializerMethodField()
    investor_count = serializers.SerializerMethodField()
    my_pool_share_bps = serializers.SerializerMethodField()
    my_earnings_cents = serializers.SerializerMethodField()
    my_pending_returns_cents = serializers.SerializerMethodField()
    pending_returns_cents = serializers.SerializerMethodField()
    repayment_success_pct = serializers.SerializerMethodField()
    interest_series = serializers.SerializerMethodField()

    class Meta:
        model = Pool
        fields = (
            "id",
            "name",
            "type",
            "status",
            "closed",
            "owner_investor",
            "countries",
            "industries",
            "strategy",
            "min_deposit_cents",
            "target_size_cents",
            "exposure_limit_percent",
            "auto_funding",
            "allow_public",
            "target_return_bps",
            "loan_tiers",
            "current_epoch",
            "my_principal_cents",
            "total_principal_cents",
            "deployed_cents",
            "available_liquidity_cents",
            "utilization_pct",
            "investor_count",
            "my_pool_share_bps",
            "my_earnings_cents",
            "my_pending_returns_cents",
            "pending_returns_cents",
            "repayment_success_pct",
            "interest_series",
            "created_at",
        )

    def get_current_epoch(self, obj):
        epoch = obj.epochs.exclude(state="closed").order_by("-index").first()
        if not epoch:
            return None
        return {
            "id": str(epoch.id),
            "index": epoch.index,
            "starts_at": epoch.starts_at,
            "ends_at": epoch.ends_at,
            "state": epoch.state,
            "withdrawal_window_start": epoch.withdrawal_window_start,
            "withdrawal_window_end": epoch.withdrawal_window_end,
        }

    def _my_position(self, obj):
        request = self.context.get("request")
        if not request or not getattr(request.user, "is_authenticated", False):
            return None
        if not hasattr(request.user, "investor_profile"):
            return None
        return obj.positions.filter(investor=request.user.investor_profile).first()

    def get_my_principal_cents(self, obj):
        pos = self._my_position(obj)
        if pos is None and not (
            self.context.get("request")
            and getattr(self.context["request"].user, "is_authenticated", False)
            and hasattr(self.context["request"].user, "investor_profile")
        ):
            return None
        return pos.principal_cents if pos else 0

    def get_total_principal_cents(self, obj):
        return obj.positions.aggregate(s=Sum("principal_cents"))["s"] or 0

    def get_deployed_cents(self, obj):
        from invoices.models import Invoice

        # Funded principal still active — not outstanding (which includes interest).
        return (
            Invoice.objects.filter(pool=obj, funded_amount_cents__gt=0)
            .exclude(finance_step=Invoice.FinanceStep.FINANCE_REPAID)
            .aggregate(s=Sum("funded_amount_cents"))["s"]
            or 0
        )

    def get_available_liquidity_cents(self, obj):
        principal = self.get_total_principal_cents(obj)
        return max(0, principal - self.get_deployed_cents(obj))

    def get_utilization_pct(self, obj):
        principal = self.get_total_principal_cents(obj)
        if not principal:
            return 0
        return min(100, round(100 * self.get_deployed_cents(obj) / principal))

    def get_investor_count(self, obj):
        return obj.positions.filter(principal_cents__gt=0).count()

    def get_my_pool_share_bps(self, obj):
        pos = self._my_position(obj)
        if pos is None:
            return None
        total = obj.positions.aggregate(s=Sum("principal_cents"))["s"] or 0
        if not total:
            return 0
        return round(10_000 * pos.principal_cents / total)

    def get_my_earnings_cents(self, obj):
        request = self.context.get("request")
        if not request or not getattr(request.user, "is_authenticated", False):
            return None
        from balances.activity import return_queryset

        return return_queryset(request.user).filter(pool=obj).aggregate(s=Sum("amount_cents"))["s"] or 0

    def get_my_pending_returns_cents(self, obj):
        request = self.context.get("request")
        if not request or not getattr(request.user, "is_authenticated", False):
            return None
        from balances.models import BalanceTransaction

        return (
            BalanceTransaction.objects.filter(
                balance__user=request.user,
                pool=obj,
                type=BalanceTransaction.Type.RETURN,
                status=BalanceTransaction.Status.PENDING,
            ).aggregate(s=Sum("amount_cents"))["s"]
            or 0
        )

    def get_pending_returns_cents(self, obj):
        from balances.models import BalanceTransaction

        return (
            BalanceTransaction.objects.filter(
                pool=obj,
                type=BalanceTransaction.Type.RETURN,
                status=BalanceTransaction.Status.PENDING,
            ).aggregate(s=Sum("amount_cents"))["s"]
            or 0
        )

    def get_repayment_success_pct(self, obj):
        from invoices.models import Invoice

        funded = Invoice.objects.filter(pool=obj, funded_amount_cents__gt=0)
        total = funded.count()
        if not total:
            return None
        repaid = funded.filter(finance_step=Invoice.FinanceStep.FINANCE_REPAID).count()
        return round(100 * repaid / total)

    def get_interest_series(self, obj):
        from balances.activity import interest_series_for, return_queryset

        return interest_series_for(return_queryset().filter(pool=obj))


class CustomPoolCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255)
    countries = serializers.ListField(child=serializers.CharField(), required=False)
    industries = serializers.ListField(child=serializers.CharField(), required=False)
    exposure_limit_percent = serializers.DecimalField(max_digits=5, decimal_places=2, required=False)
    auto_funding = serializers.BooleanField(required=False, default=True)
    allow_public = serializers.BooleanField(required=False, default=False)
    min_deposit_cents = serializers.IntegerField(required=False, min_value=1)
    target_return_bps = serializers.IntegerField(required=False)
    strategy = serializers.CharField(required=False, allow_blank=True)
    tiers = PoolLoanTierSerializer(many=True, required=False)


class AdminPoolCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255)
    countries = serializers.ListField(child=serializers.CharField(), required=False)
    industries = serializers.ListField(child=serializers.CharField(), required=False)
    min_deposit_cents = serializers.IntegerField(required=False, min_value=1)
    target_size_cents = serializers.IntegerField(required=False)
    target_return_bps = serializers.IntegerField(required=False)
    strategy = serializers.CharField(required=False, allow_blank=True)
    exposure_limit_percent = serializers.DecimalField(max_digits=5, decimal_places=2, required=False)
    tiers = PoolLoanTierSerializer(many=True, required=False)


class AmountSerializer(serializers.Serializer):
    amount_cents = serializers.IntegerField(min_value=1)
    idempotency_key = serializers.CharField(required=False, allow_blank=True)


class PoolWithdrawalSerializer(serializers.ModelSerializer):
    investor_name = serializers.SerializerMethodField()
    investor_email = serializers.SerializerMethodField()

    class Meta:
        model = PoolWithdrawalRequest
        fields = (
            "id",
            "pool",
            "investor",
            "investor_name",
            "investor_email",
            "amount_cents",
            "pool_share_bps_snapshot",
            "status",
            "requested_at",
        )

    def get_investor_name(self, obj):
        user = obj.investor.user
        return user.full_name or user.email

    def get_investor_email(self, obj):
        return obj.investor.user.email


class DecideSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(choices=["accept", "reject"])
