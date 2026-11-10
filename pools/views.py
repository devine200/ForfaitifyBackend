from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from common.permissions import HasApprovedKyc, IsAdmin, IsInvestor
from pools.models import Pool, PoolLoanTier, PoolWithdrawalRequest
from pools.serializers import (
    AdminPoolCreateSerializer,
    AmountSerializer,
    CustomPoolCreateSerializer,
    DecideSerializer,
    PoolSerializer,
    PoolWithdrawalSerializer,
)
from pools.services import (
    decide_pool_withdrawal,
    deposit_into_pool,
    ensure_current_epoch,
    request_pool_withdrawal,
    settle_pool_withdrawal,
)


def _create_tiers(pool, tiers_data):
    for t in tiers_data or []:
        PoolLoanTier.objects.create(pool=pool, **t)


def _replace_tiers(pool, tiers_data):
    if tiers_data is None:
        return
    pool.loan_tiers.all().delete()
    _create_tiers(pool, tiers_data)


def _can_access_private_pool(user, pool: Pool) -> bool:
    if getattr(user, "is_admin", False):
        return True
    if pool.allow_public:
        return True
    if hasattr(user, "investor_profile"):
        investor = user.investor_profile
        if pool.owner_investor_id == investor.id:
            return True
        if pool.positions.filter(investor=investor).exists():
            return True
    return False


class PoolListView(generics.ListAPIView):
    serializer_class = PoolSerializer

    def get_queryset(self):
        qs = Pool.objects.prefetch_related("loan_tiers", "epochs", "positions")
        pool_type = self.request.query_params.get("type")
        status_q = self.request.query_params.get("status")
        mine = self.request.query_params.get("mine")
        closed = self.request.query_params.get("closed")
        if pool_type:
            qs = qs.filter(type=pool_type)
        if status_q:
            qs = qs.filter(status=status_q)
        if closed is not None:
            qs = qs.filter(closed=closed.lower() in ("1", "true", "yes"))
        if mine and hasattr(self.request.user, "investor_profile"):
            qs = qs.filter(positions__investor=self.request.user.investor_profile)
        user = self.request.user
        if getattr(user, "is_admin", False):
            return qs.distinct()
        if hasattr(user, "investor_profile"):
            investor = user.investor_profile
            from django.db.models import Q

            qs = qs.filter(
                Q(allow_public=True)
                | Q(owner_investor=investor)
                | Q(positions__investor=investor)
            )
        else:
            qs = qs.filter(allow_public=True)
        return qs.distinct()


class PoolDetailView(generics.RetrieveAPIView):
    serializer_class = PoolSerializer
    queryset = Pool.objects.prefetch_related("loan_tiers", "epochs", "positions")


class CustomPoolCreateView(APIView):
    permission_classes = [IsInvestor, HasApprovedKyc]

    def post(self, request):
        ser = CustomPoolCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        tiers = data.pop("tiers", [])
        auto_funding = data.get("auto_funding", True)
        allow_public = data.get("allow_public", False) if auto_funding else False
        pool = Pool.objects.create(
            type=Pool.Type.CUSTOM,
            owner_investor=request.user.investor_profile,
            created_by=request.user,
            name=data["name"],
            countries=data.get("countries", []),
            industries=data.get("industries", []),
            exposure_limit_percent=data.get("exposure_limit_percent", 15),
            auto_funding=auto_funding,
            allow_public=allow_public,
            min_deposit_cents=data.get("min_deposit_cents", 10000),
            target_return_bps=data.get("target_return_bps"),
            strategy=data.get("strategy", ""),
        )
        _create_tiers(pool, tiers)
        ensure_current_epoch(pool)
        return Response(PoolSerializer(pool, context={"request": request}).data, status=201)


class CustomPoolUpdateView(APIView):
    permission_classes = [IsInvestor]

    def patch(self, request, pk):
        pool = Pool.objects.get(pk=pk, type=Pool.Type.CUSTOM)
        if pool.owner_investor_id != request.user.investor_profile.id:
            return Response({"detail": "Not your pool."}, status=403)
        ser = CustomPoolCreateSerializer(data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        tiers = data.pop("tiers", None)
        for field in (
            "name",
            "countries",
            "industries",
            "auto_funding",
            "allow_public",
            "min_deposit_cents",
            "target_return_bps",
            "strategy",
        ):
            if field in data:
                setattr(pool, field, data[field])
        if "exposure_limit_percent" in data:
            # tighten-only after deposits
            if pool.positions.exists() and data["exposure_limit_percent"] > pool.exposure_limit_percent:
                return Response({"detail": "Cannot raise exposure after deposits."}, status=400)
            pool.exposure_limit_percent = data["exposure_limit_percent"]
        if pool.auto_funding is False:
            pool.allow_public = False
        pool.save()
        _replace_tiers(pool, tiers)
        return Response(PoolSerializer(pool, context={"request": request}).data)


class AdminPoolCreateView(APIView):
    permission_classes = [IsAdmin]

    def post(self, request):
        ser = AdminPoolCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        tiers = data.pop("tiers", [])
        auto_funding = data.get("auto_funding", True)
        allow_public = data.get("allow_public", True) if auto_funding else False
        pool = Pool.objects.create(
            type=Pool.Type.CENTRALIZED,
            created_by=request.user,
            name=data["name"],
            countries=data.get("countries", []),
            industries=data.get("industries", []),
            min_deposit_cents=data.get("min_deposit_cents", 10000),
            target_size_cents=data.get("target_size_cents"),
            target_return_bps=data.get("target_return_bps"),
            strategy=data.get("strategy", ""),
            exposure_limit_percent=data.get("exposure_limit_percent", 15),
            auto_funding=auto_funding,
            allow_public=allow_public,
        )
        _create_tiers(pool, tiers)
        ensure_current_epoch(pool)
        return Response(PoolSerializer(pool, context={"request": request}).data, status=201)


class AdminPoolUpdateView(APIView):
    permission_classes = [IsAdmin]

    def patch(self, request, pk):
        pool = Pool.objects.get(pk=pk)
        ser = AdminPoolCreateSerializer(data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        tiers = data.pop("tiers", None)
        for field in (
            "name",
            "countries",
            "industries",
            "min_deposit_cents",
            "target_size_cents",
            "target_return_bps",
            "strategy",
            "exposure_limit_percent",
            "auto_funding",
            "allow_public",
        ):
            if field in data:
                setattr(pool, field, data[field])
        if "status" in request.data:
            pool.status = request.data["status"]
        if pool.auto_funding is False:
            pool.allow_public = False
        pool.save()
        _replace_tiers(pool, tiers)
        return Response(PoolSerializer(pool, context={"request": request}).data)


class AdminPoolCloseView(APIView):
    permission_classes = [IsAdmin]

    def post(self, request, pk):
        pool = Pool.objects.get(pk=pk)
        pool.closed = True
        pool.status = Pool.Status.INACTIVE
        pool.save(update_fields=["closed", "status", "updated_at"])
        return Response(PoolSerializer(pool, context={"request": request}).data)


class PoolDepositView(APIView):
    permission_classes = [IsInvestor, HasApprovedKyc]

    def post(self, request, pk):
        ser = AmountSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        pool = Pool.objects.get(pk=pk)
        if not _can_access_private_pool(request.user, pool):
            return Response(
                {"detail": "This pool is invite-only and not open for public investment."},
                status=403,
            )
        idem = ser.validated_data.get("idempotency_key") or request.headers.get("Idempotency-Key")
        position = deposit_into_pool(
            pool,
            request.user.investor_profile,
            ser.validated_data["amount_cents"],
            idempotency_key=idem,
        )
        return Response(
            {"pool_id": str(pool.id), "principal_cents": position.principal_cents},
            status=status.HTTP_201_CREATED,
        )


class PoolWithdrawalCreateView(APIView):
    permission_classes = [IsInvestor, HasApprovedKyc]

    def post(self, request, pk):
        ser = AmountSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        pool = Pool.objects.get(pk=pk)
        req = request_pool_withdrawal(
            pool,
            request.user.investor_profile,
            ser.validated_data["amount_cents"],
        )
        return Response(PoolWithdrawalSerializer(req).data, status=201)


class PoolWithdrawalListView(generics.ListAPIView):
    serializer_class = PoolWithdrawalSerializer

    def get_queryset(self):
        qs = PoolWithdrawalRequest.objects.filter(pool_id=self.kwargs["pk"])
        if not getattr(self.request.user, "is_admin", False):
            if hasattr(self.request.user, "investor_profile"):
                qs = qs.filter(investor=self.request.user.investor_profile)
            else:
                qs = qs.none()
        return qs


class AdminPoolWithdrawalDecideView(APIView):
    permission_classes = [IsAdmin]

    def post(self, request, pk):
        ser = DecideSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        req = PoolWithdrawalRequest.objects.get(pk=pk)
        decide_pool_withdrawal(req, ser.validated_data["decision"])
        return Response(PoolWithdrawalSerializer(req).data)


class PoolWithdrawalSettleView(APIView):
    permission_classes = [IsAdmin]

    def post(self, request, pool_id, pk):
        req = PoolWithdrawalRequest.objects.get(pk=pk, pool_id=pool_id)
        settle_pool_withdrawal(req)
        return Response(PoolWithdrawalSerializer(req).data)
