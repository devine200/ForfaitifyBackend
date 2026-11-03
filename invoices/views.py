from django.db.models import Sum
from rest_framework import generics
from rest_framework.response import Response
from rest_framework.views import APIView

from common.permissions import HasApprovedKyb, IsAdmin, IsInvestor, IsMerchant
from invoices.models import Invoice, InvoiceAcknowledgement, InvoiceDocument
from invoices.serializers import (
    FundSerializer,
    InsuranceSerializer,
    InvoiceCreateSerializer,
    InvoiceDocumentSerializer,
    InvoiceSerializer,
    RepaySerializer,
    ReviewSerializer,
    WithdrawFundingSerializer,
)
from invoices.services import (
    fund_invoice,
    generate_invoice_code,
    repay_invoice,
    review_invoice,
    set_insurance,
    withdraw_funding,
)
from notifications.emit import emit
from notifications.keys import key
from payments.models import PayoutMethod
from pools.models import Pool


class MerchantDashboardView(APIView):
    permission_classes = [IsMerchant]

    def get(self, request):
        from balances.activity import flow, percent_change, period_bounds
        from balances.models import BalanceTransaction

        invoices = Invoice.objects.filter(merchant=request.user.merchant_profile)
        _now, current_start, previous_start = period_bounds()
        inflow_types = [BalanceTransaction.Type.FUNDING, BalanceTransaction.Type.DEPOSIT]
        outflow_types = [
            BalanceTransaction.Type.WITHDRAWAL,
            BalanceTransaction.Type.REPAYMENT,
            BalanceTransaction.Type.FEE,
        ]
        inflows = flow(request.user, inflow_types, current_start, _now)
        inflows_prev = flow(request.user, inflow_types, previous_start, current_start)
        outflows = flow(request.user, outflow_types, current_start, _now)
        outflows_prev = flow(request.user, outflow_types, previous_start, current_start)
        repayments = flow(request.user, [BalanceTransaction.Type.REPAYMENT], current_start, _now)
        repayments_prev = flow(request.user, [BalanceTransaction.Type.REPAYMENT], previous_start, current_start)
        fees = flow(request.user, [BalanceTransaction.Type.FEE], current_start, _now)
        funding = flow(request.user, [BalanceTransaction.Type.FUNDING], current_start, _now)
        funding_prev = flow(request.user, [BalanceTransaction.Type.FUNDING], previous_start, current_start)
        awaiting = (
            invoices.filter(payout_status__in=["ready", "pending"]).aggregate(s=Sum("funded_amount_cents"))["s"] or 0
        )
        due = (
            invoices.filter(payout_status="settled")
            .exclude(finance_step="finance_repaid")
            .aggregate(s=Sum("outstanding_cents"))["s"]
            or 0
        )
        settled = invoices.filter(payout_status="settled")
        settled_count = settled.count()
        on_time = settled.exclude(repayment_state="overdue").count()
        closed = invoices.filter(finance_step="finance_repaid").count()
        return Response(
            {
                "invoice_count": invoices.count(),
                "outstanding_cents": invoices.aggregate(s=Sum("outstanding_cents"))["s"] or 0,
                "funded_cents": invoices.aggregate(s=Sum("funded_amount_cents"))["s"] or 0,
                "pending_review": invoices.filter(review_status="pending_review").count(),
                "ready_to_withdraw": invoices.filter(payout_status="ready").count(),
                "period_label": "30D",
                "period_inflows_cents": inflows,
                "period_outflows_cents": outflows,
                "net_cashflow_cents": inflows - outflows,
                "inflows_delta": percent_change(inflows, inflows_prev),
                "outflows_delta": percent_change(outflows, outflows_prev),
                "net_cashflow_delta": percent_change(inflows - outflows, inflows_prev - outflows_prev),
                "funding_received_cents": funding,
                "funding_received_delta": percent_change(funding, funding_prev),
                "awaiting_withdrawal_cents": awaiting,
                "due_for_repayment_cents": due,
                "repayments_cents": repayments,
                "repayments_delta": percent_change(repayments, repayments_prev),
                "fees_cents": fees,
                "invoices_closed": closed,
                "overdue_count": invoices.filter(repayment_state="overdue").count(),
                "on_time_rate": round(100 * on_time / settled_count) if settled_count else None,
                "completed_financing": invoices.filter(funded_amount_cents__gt=0).count(),
            }
        )


class MerchantInvoiceListCreateView(APIView):
    permission_classes = [IsMerchant]

    def get(self, request):
        qs = Invoice.objects.filter(merchant=request.user.merchant_profile).prefetch_related(
            "documents", "cosigners"
        )
        status_q = request.query_params.get("status")
        if status_q:
            qs = qs.filter(display_status=status_q)
        return Response(InvoiceSerializer(qs, many=True).data)

    def post(self, request):
        if not HasApprovedKyb().has_permission(request, self):
            return Response({"detail": HasApprovedKyb.message, "code": "kyb"}, status=403)
        ser = InvoiceCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        if not (
            data["ack_repayment_terms"]
            and data["ack_late_penalties"]
            and data["ack_contract_enforcement"]
        ):
            return Response({"detail": "All acknowledgements required."}, status=400)

        loan = data["loan_amount_cents"]
        total = data.get("total_amount_cents") or loan
        invoice = Invoice.objects.create(
            code=generate_invoice_code(),
            name=data["name"],
            title=data.get("title") or data["name"],
            merchant=request.user.merchant_profile,
            buyer_name=data.get("buyer_name", ""),
            industry=data.get("industry") or request.user.merchant_profile.industry,
            country=data.get("country") or request.user.country,
            years_in_operation_snapshot=data.get("years_in_operation")
            or request.user.merchant_profile.years_in_operation,
            loan_amount_cents=loan,
            total_amount_cents=total,
            amount_left_cents=loan,
            duration_days=data["duration_days"],
            repayment_amount_cents=loan,
            outstanding_cents=0,
        )
        for kind, flag in (
            (InvoiceAcknowledgement.Kind.REPAYMENT_TERMS, "ack_repayment_terms"),
            (InvoiceAcknowledgement.Kind.LATE_PENALTIES, "ack_late_penalties"),
            (InvoiceAcknowledgement.Kind.CONTRACT_ENFORCEMENT, "ack_contract_enforcement"),
        ):
            if data[flag]:
                InvoiceAcknowledgement.objects.create(invoice=invoice, kind=kind)

        upload = request.FILES.get("file")
        if upload:
            InvoiceDocument.objects.create(invoice=invoice, name=upload.name, file=upload)

        emit(
            event_type="invoice.created",
            user=request.user,
            notify_admins=True,
            role_scope="merchant",
            notification={
                "category": "invoiceUpdates",
                "kind": "send",
                "title": f"Invoice {invoice.code} submitted",
                "body": "Your receivable is pending review.",
                "href": f"/merchant/invoices/{invoice.id}",
            },
            invalidate=[
                key("merchantInvoices"),
                key("merchantInvoice", str(invoice.id)),
                key("merchantDashboard"),
                key("adminInvoices"),
                key("adminDashboard"),
                key("notifications"),
            ],
            email=False,
        )
        return Response(InvoiceSerializer(invoice).data, status=201)


class MerchantInvoiceDetailView(generics.RetrieveAPIView):
    permission_classes = [IsMerchant]
    serializer_class = InvoiceSerializer

    def get_queryset(self):
        return Invoice.objects.filter(merchant=self.request.user.merchant_profile).prefetch_related(
            "documents", "cosigners"
        )


class MerchantInvoiceDocumentView(APIView):
    permission_classes = [IsMerchant]

    def post(self, request, pk):
        invoice = Invoice.objects.get(pk=pk, merchant=request.user.merchant_profile)
        upload = request.FILES.get("file")
        if not upload:
            return Response({"detail": "file required"}, status=400)
        doc = InvoiceDocument.objects.create(
            invoice=invoice,
            name=request.data.get("name") or upload.name,
            file=upload,
            visibility=request.data.get("visibility") or "available",
        )
        return Response(InvoiceDocumentSerializer(doc).data, status=201)


class MerchantWithdrawFundingView(APIView):
    permission_classes = [IsMerchant, HasApprovedKyb]

    def post(self, request, pk):
        ser = WithdrawFundingSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        invoice = Invoice.objects.get(pk=pk, merchant=request.user.merchant_profile)
        method = PayoutMethod.objects.filter(
            user=request.user, id=ser.validated_data["payout_method_id"]
        ).first()
        if not method:
            return Response({"detail": "Payout method not found."}, status=404)
        withdraw_funding(invoice, method)
        return Response(InvoiceSerializer(invoice).data)


class MerchantRepayView(APIView):
    permission_classes = [IsMerchant, HasApprovedKyb]

    def post(self, request, pk):
        ser = RepaySerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        invoice = Invoice.objects.get(pk=pk, merchant=request.user.merchant_profile)
        repay_invoice(invoice, ser.validated_data["amount_cents"])
        return Response(InvoiceSerializer(invoice).data)


class MerchantPoolBrowseView(generics.ListAPIView):
    permission_classes = [IsMerchant]
    from pools.serializers import PoolSerializer

    serializer_class = PoolSerializer

    def get_queryset(self):
        from pools.models import Pool

        return Pool.objects.filter(status="active", closed=False)


class InvestorDashboardView(APIView):
    permission_classes = [IsInvestor]

    def get(self, request):
        from balances.activity import (
            earning_streak_months,
            flow,
            interest_series_for,
            percent_change,
            period_bounds,
            return_queryset,
        )
        from balances.models import BalanceTransaction
        from balances.services import get_or_create_balance
        from pools.models import PoolPosition

        positions = PoolPosition.objects.filter(investor=request.user.investor_profile)
        deployed = positions.aggregate(s=Sum("principal_cents"))["s"] or 0
        custom = positions.filter(pool__type="custom").aggregate(s=Sum("principal_cents"))["s"] or 0
        central = positions.filter(pool__type="centralized").aggregate(s=Sum("principal_cents"))["s"] or 0
        balance = get_or_create_balance(request.user)
        _now, current_start, previous_start = period_bounds()
        inflow_types = [
            BalanceTransaction.Type.DEPOSIT,
            BalanceTransaction.Type.RETURN,
            BalanceTransaction.Type.POOL_WITHDRAW,
        ]
        outflow_types = [
            BalanceTransaction.Type.WITHDRAWAL,
            BalanceTransaction.Type.POOL_ALLOCATE,
            BalanceTransaction.Type.FEE,
        ]
        inflows = flow(request.user, inflow_types, current_start, _now)
        inflows_prev = flow(request.user, inflow_types, previous_start, current_start)
        outflows = flow(request.user, outflow_types, current_start, _now)
        outflows_prev = flow(request.user, outflow_types, previous_start, current_start)
        returns = flow(request.user, [BalanceTransaction.Type.RETURN], current_start, _now)
        fees = flow(request.user, [BalanceTransaction.Type.FEE], current_start, _now)
        pending_returns = (
            BalanceTransaction.objects.filter(
                balance__user=request.user,
                type=BalanceTransaction.Type.RETURN,
                status=BalanceTransaction.Status.PENDING,
            ).aggregate(s=Sum("amount_cents"))["s"]
            or 0
        )
        equity = balance.available_cents + balance.held_cents + deployed
        streak = earning_streak_months(request.user)
        returns_all = return_queryset(request.user).aggregate(s=Sum("amount_cents"))["s"] or 0
        return Response(
            {
                "total_invested_cents": deployed,
                "active_positions": positions.filter(principal_cents__gt=0).count(),
                "available_cents": balance.available_cents,
                "held_cents": balance.held_cents,
                "updated_at": balance.updated_at,
                "equity_cents": equity,
                "deployed_cents": deployed,
                "pending_returns_cents": pending_returns,
                "utilization_pct": round(100 * deployed / equity) if equity else 0,
                "custom_principal_cents": custom,
                "central_principal_cents": central,
                "period_label": "30D",
                "inflows_cents": inflows,
                "outflows_cents": outflows,
                "net_cashflow_cents": inflows - outflows,
                "inflows_delta": percent_change(inflows, inflows_prev),
                "outflows_delta": percent_change(outflows, outflows_prev),
                "net_cashflow_delta": percent_change(inflows - outflows, inflows_prev - outflows_prev),
                "net_pnl_cents": returns - fees,
                "earnings_to_date_cents": returns_all,
                "earning_streak_months": streak,
                "range": request.query_params.get("range", "monthly"),
                "interest_series": interest_series_for(return_queryset(request.user)),
            }
        )


class InvestorInvoiceListView(generics.ListAPIView):
    permission_classes = [IsInvestor]
    serializer_class = InvoiceSerializer

    def get_queryset(self):
        qs = Invoice.objects.filter(
            review_status=Invoice.ReviewStatus.APPROVED,
            inactive=False,
        ).prefetch_related("documents", "cosigners")
        pool_id = self.request.query_params.get("pool_id")
        if pool_id:
            qs = qs.filter(pool_id=pool_id)
        return qs


class InvestorInvoiceDetailView(generics.RetrieveAPIView):
    permission_classes = [IsInvestor]
    serializer_class = InvoiceSerializer
    queryset = Invoice.objects.prefetch_related("documents", "cosigners")


class AdminDashboardView(APIView):
    permission_classes = [IsAdmin]

    def get(self, request):
        from balances.activity import interest_series_for, percent_change, period_bounds, return_queryset
        from payments.models import PaymentIntent
        from pools.models import PoolPosition

        now, current_start, previous_start = period_bounds()

        def intent_sum(kind, start, end):
            return (
                PaymentIntent.objects.filter(
                    kind=kind,
                    status=PaymentIntent.Status.SUCCESSFUL,
                    created_at__gte=start,
                    created_at__lt=end,
                ).aggregate(s=Sum("amount_cents"))["s"]
                or 0
            )

        deposits = intent_sum("deposit", current_start, now)
        deposits_prev = intent_sum("deposit", previous_start, current_start)
        withdrawals = intent_sum("withdrawal", current_start, now)
        withdrawals_prev = intent_sum("withdrawal", previous_start, current_start)
        from balances.models import Balance, BalanceTransaction

        pending = PaymentIntent.objects.filter(
            kind="withdrawal", status="pending", requires_admin_review=True
        )
        aum = PoolPosition.objects.aggregate(s=Sum("principal_cents"))["s"] or 0
        deployed = (
            Invoice.objects.filter(funded_amount_cents__gt=0)
            .exclude(finance_step=Invoice.FinanceStep.FINANCE_REPAID)
            .aggregate(s=Sum("outstanding_cents"))["s"]
            or 0
        )
        cash = Balance.objects.aggregate(s=Sum("available_cents"))["s"] or 0
        fees = (
            BalanceTransaction.objects.filter(
                type=BalanceTransaction.Type.FEE,
                status=BalanceTransaction.Status.SUCCESSFUL,
                created_at__gte=current_start,
                created_at__lt=now,
            ).aggregate(s=Sum("amount_cents"))["s"]
            or 0
        )
        fees_prev = (
            BalanceTransaction.objects.filter(
                type=BalanceTransaction.Type.FEE,
                status=BalanceTransaction.Status.SUCCESSFUL,
                created_at__gte=previous_start,
                created_at__lt=current_start,
            ).aggregate(s=Sum("amount_cents"))["s"]
            or 0
        )
        return Response(
            {
                "pending_review_count": Invoice.objects.filter(
                    review_status=Invoice.ReviewStatus.PENDING_REVIEW
                ).count(),
                "overdue_count": Invoice.objects.filter(repayment_state="overdue").count(),
                "outstanding_cents": Invoice.objects.aggregate(s=Sum("outstanding_cents"))["s"] or 0,
                "pending_withdrawals": pending.count(),
                "pending_withdrawal_cents": pending.aggregate(s=Sum("amount_cents"))["s"] or 0,
                "period_label": "30D",
                "deposits_cents": deposits,
                "deposits_delta": percent_change(deposits, deposits_prev),
                "withdrawals_cents": withdrawals,
                "withdrawals_delta": percent_change(withdrawals, withdrawals_prev),
                "net_flow_cents": deposits - withdrawals,
                "net_flow_delta": percent_change(deposits - withdrawals, deposits_prev - withdrawals_prev),
                "invested_aum_cents": aum,
                "available_liquidity_cents": max(0, aum - deployed) + cash,
                "platform_revenue_cents": fees,
                "platform_revenue_delta": percent_change(fees, fees_prev),
                "interest_series": interest_series_for(return_queryset()),
            }
        )


class AdminInvoiceListView(generics.ListAPIView):
    permission_classes = [IsAdmin]
    serializer_class = InvoiceSerializer

    def get_queryset(self):
        qs = Invoice.objects.prefetch_related("documents", "cosigners")
        queue = self.request.query_params.get("queue")
        if queue == "pending":
            qs = qs.filter(review_status=Invoice.ReviewStatus.PENDING_REVIEW)
        elif queue == "overdue":
            qs = qs.filter(repayment_state="overdue")
        return qs


class AdminInvoiceDetailView(generics.RetrieveAPIView):
    permission_classes = [IsAdmin]
    serializer_class = InvoiceSerializer
    queryset = Invoice.objects.prefetch_related("documents", "cosigners")


class AdminInvoiceReviewView(APIView):
    permission_classes = [IsAdmin]

    def post(self, request, pk):
        ser = ReviewSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        invoice = Invoice.objects.get(pk=pk)
        review_invoice(invoice, ser.validated_data["decision"])
        return Response(InvoiceSerializer(invoice).data)


class AdminInvoiceInsuranceView(APIView):
    permission_classes = [IsAdmin]

    def patch(self, request, pk):
        ser = InsuranceSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        invoice = Invoice.objects.get(pk=pk)
        set_insurance(invoice, ser.validated_data["status"])
        return Response(InvoiceSerializer(invoice).data)


class AdminInvoiceFundView(APIView):
    permission_classes = [IsAdmin]

    def post(self, request, pk):
        ser = FundSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        invoice = Invoice.objects.get(pk=pk)
        pool = Pool.objects.get(pk=ser.validated_data["pool_id"])
        fund_invoice(invoice, pool)
        return Response(InvoiceSerializer(invoice).data)
