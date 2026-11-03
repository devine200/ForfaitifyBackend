from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from balances.models import BalanceTransaction
from balances.services import (
    credit_available,
    debit_available,
    reject_hold_for_intent,
    release_hold_for_intent,
    try_auto_repay_after_credit,
)
from common.permissions import HasApprovedActorVerification, IsAdmin, IsMerchantOrInvestor
from notifications.emit import emit
from notifications.formatting import format_usd
from notifications.keys import key, money_actor_keys, role_dashboard
from payments.models import PaymentIntent, PayoutMethod
from payments.serializers import (
    DepositSerializer,
    LedgerDecideSerializer,
    PaymentIntentSerializer,
    PayoutMethodSerializer,
    WithdrawalSerializer,
)
from utils import payments as payment_util


def _actor_portal(user, role: str | None) -> str:
    if role in ("merchant", "investor"):
        return role
    if getattr(user, "has_investor", False) and not getattr(user, "has_merchant", False):
        return "investor"
    return "merchant"


def _emit_deposit_success(user, intent: PaymentIntent, role: str | None = None):
    portal = _actor_portal(user, role)
    dash = role_dashboard(user, portal)
    emit(
        event_type="payment.deposit.succeeded",
        user=user,
        role_scope=portal,
        notification={
            "category": "deposits",
            "kind": "send",
            "title": f"Deposit of {format_usd(intent.amount_cents)} confirmed",
            "body": "Funds are available in your balance.",
            "href": "/merchant/balance" if portal == "merchant" else "/investor/balance",
        },
        invalidate=money_actor_keys(dashboard=dash) + [key("adminDashboard")],
        email="money",
        idempotency_key=f"email:payment.deposit.succeeded:{intent.id}",
        email_context={"amount_cents": intent.amount_cents, "fact_label": "Status", "fact_value": "Successful"},
    )


def _emit_withdrawal_submitted(user, intent: PaymentIntent, role: str | None = None):
    portal = _actor_portal(user, role)
    dash = role_dashboard(user, portal)
    keys = money_actor_keys(dashboard=dash) + [key("adminDashboard"), key("adminLedger")]
    emit(
        event_type="payment.withdrawal.submitted",
        user=user,
        notify_admins=True,
        role_scope=portal,
        notification={
            "category": "deposits",
            "kind": "warn",
            "title": f"Withdrawal of {format_usd(intent.amount_cents)} submitted",
            "body": "Your withdrawal is pending review before payout.",
            "urgent": True,
            "href": "/merchant/balance" if portal == "merchant" else "/investor/balance",
        },
        invalidate=keys,
        email="money",
        idempotency_key=f"email:payment.withdrawal.submitted:{intent.id}",
        email_context={"amount_cents": intent.amount_cents, "fact_label": "Status", "fact_value": "Pending review"},
    )


def _emit_withdrawal_decided(user, intent: PaymentIntent, approved: bool):
    dash = role_dashboard(user)
    status_label = "approved" if approved else "rejected"
    emit(
        event_type="payment.withdrawal.decided",
        user=user,
        notify_admins=True,
        role_scope="merchant" if getattr(user, "has_merchant", False) else "investor",
        notification={
            "category": "deposits",
            "kind": "send" if approved else "alert",
            "title": f"Withdrawal {status_label}: {format_usd(intent.amount_cents)}",
            "body": (
                "Funds have been released for payout."
                if approved
                else "The held amount was returned to your available balance."
            ),
            "urgent": not approved,
            "href": "/merchant/balance" if getattr(user, "has_merchant", False) else "/investor/balance",
        },
        invalidate=money_actor_keys(dashboard=dash) + [key("adminDashboard"), key("adminLedger")],
        email="money",
        idempotency_key=f"email:payment.withdrawal.decided:{intent.id}:{status_label}",
        email_context={
            "amount_cents": intent.amount_cents,
            "decision": status_label,
        },
    )


def _settle_deposit(intent: PaymentIntent, *, role: str | None = None) -> None:
    credit_key = f"dep-credit-{intent.id}"
    already_credited = BalanceTransaction.objects.filter(idempotency_key=credit_key).exists()
    if intent.status != PaymentIntent.Status.SUCCESSFUL:
        intent.status = PaymentIntent.Status.SUCCESSFUL
        intent.settled_at = timezone.now()
        intent.save(update_fields=["status", "settled_at", "updated_at"])
    credit_available(
        intent.user,
        intent.amount_cents,
        tx_type=BalanceTransaction.Type.DEPOSIT,
        destination_label="Balance deposit",
        payment_intent=intent,
        idempotency_key=credit_key,
    )
    if already_credited:
        return
    _emit_deposit_success(intent.user, intent, role)
    try_auto_repay_after_credit(intent.user)


def _approve_payout_intent(intent: PaymentIntent) -> PaymentIntent:
    """Admin approve → processor transfer → release hold (and settle invoice if any)."""
    if intent.status != PaymentIntent.Status.PENDING:
        raise ValueError("Not pending.")
    method = intent.payout_method
    account_ref = method.account_ref if method else ""
    transfer = payment_util.initiate_transfer(
        processor_ref=intent.processor_ref or str(intent.id),
        user_id=str(intent.user_id),
        amount_cents=intent.amount_cents,
        payout_account_ref=account_ref,
        currency=intent.currency,
        narration=f"Forfaitify {intent.kind} {intent.id}",
    )
    meta = dict(intent.meta or {})
    meta["transfer"] = transfer.raw or {}
    meta["transfer_ref"] = transfer.processor_ref
    intent.meta = meta
    intent.admin_decision = PaymentIntent.AdminDecision.APPROVE

    if transfer.status == "successful":
        intent.status = PaymentIntent.Status.SUCCESSFUL
        intent.settled_at = timezone.now()
        intent.save(update_fields=["status", "admin_decision", "settled_at", "meta", "updated_at"])
        release_hold_for_intent(intent)
        if intent.kind == PaymentIntent.Kind.INVOICE_PAYOUT and intent.invoice_id:
            from invoices.services import mark_invoice_payout_settled

            mark_invoice_payout_settled(intent.invoice)
        _emit_withdrawal_decided(intent.user, intent, approved=True)
    elif transfer.status == "rejected":
        intent.status = PaymentIntent.Status.REJECTED
        intent.admin_decision = PaymentIntent.AdminDecision.REJECT
        intent.save(update_fields=["status", "admin_decision", "meta", "updated_at"])
        reject_hold_for_intent(intent)
        if intent.kind == PaymentIntent.Kind.INVOICE_PAYOUT and intent.invoice_id:
            from invoices.services import mark_invoice_payout_failed

            mark_invoice_payout_failed(intent.invoice)
        _emit_withdrawal_decided(intent.user, intent, approved=False)
    else:
        intent.status = PaymentIntent.Status.PROCESSING
        intent.save(update_fields=["status", "admin_decision", "meta", "updated_at"])
    return intent


class PayoutMethodListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsMerchantOrInvestor]
    serializer_class = PayoutMethodSerializer

    def get_queryset(self):
        return PayoutMethod.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        obj = serializer.save(user=self.request.user)
        if obj.is_default:
            PayoutMethod.objects.filter(user=self.request.user).exclude(pk=obj.pk).update(is_default=False)


class PayoutMethodDeleteView(generics.DestroyAPIView):
    permission_classes = [IsMerchantOrInvestor]
    serializer_class = PayoutMethodSerializer

    def get_queryset(self):
        return PayoutMethod.objects.filter(user=self.request.user)


class DepositView(APIView):
    permission_classes = [IsMerchantOrInvestor, HasApprovedActorVerification]

    def post(self, request):
        ser = DepositSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        amount = ser.validated_data["amount_cents"]
        idem = ser.validated_data.get("idempotency_key") or request.headers.get("Idempotency-Key")
        if idem:
            existing = PaymentIntent.objects.filter(idempotency_key=idem).first()
            if existing:
                return Response(PaymentIntentSerializer(existing).data)

        result = payment_util.create_deposit(
            str(request.user.id),
            amount,
            currency=settings.DEFAULT_CURRENCY,
            idempotency_key=idem,
            customer_email=getattr(request.user, "email", None),
        )
        meta = dict(result.raw or {})
        intent = PaymentIntent.objects.create(
            user=request.user,
            kind=PaymentIntent.Kind.DEPOSIT,
            amount_cents=amount,
            currency=settings.DEFAULT_CURRENCY,
            status=result.status
            if result.status in dict(PaymentIntent.Status.choices)
            else PaymentIntent.Status.PENDING,
            processor=result.processor,
            processor_ref=result.processor_ref,
            idempotency_key=idem or None,
            settled_at=timezone.now() if result.status == "successful" else None,
            meta=meta,
        )
        if result.checkout_url or result.status == "pending":
            base = settings.FRONTEND_BASE_URL.rstrip("/")
            meta["checkout_url"] = (
                result.checkout_url
                or f"{base}/payments/return?payment={intent.id}&ref={intent.processor_ref}"
            )
            if "payment=" not in meta["checkout_url"]:
                sep = "&" if "?" in meta["checkout_url"] else "?"
                meta["checkout_url"] = f"{meta['checkout_url']}{sep}payment={intent.id}"
            intent.meta = meta
            intent.save(update_fields=["meta", "updated_at"])
        if result.status == "successful":
            _settle_deposit(intent, role=ser.validated_data.get("role") or request.data.get("role"))
        return Response(PaymentIntentSerializer(intent).data, status=status.HTTP_201_CREATED)


class WithdrawalView(APIView):
    permission_classes = [IsMerchantOrInvestor, HasApprovedActorVerification]

    @transaction.atomic
    def post(self, request):
        ser = WithdrawalSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        amount = ser.validated_data["amount_cents"]
        method = PayoutMethod.objects.filter(
            user=request.user, id=ser.validated_data["payout_method_id"]
        ).first()
        if not method:
            return Response({"detail": "Payout method not found."}, status=404)
        idem = ser.validated_data.get("idempotency_key") or request.headers.get("Idempotency-Key")
        if not idem:
            return Response({"detail": "Idempotency-Key header or body field is required."}, status=400)
        existing = PaymentIntent.objects.filter(idempotency_key=idem).first()
        if existing:
            return Response(PaymentIntentSerializer(existing).data)

        result = payment_util.create_withdrawal(
            str(request.user.id),
            amount,
            method.account_ref,
            currency=settings.DEFAULT_CURRENCY,
            idempotency_key=idem,
        )
        intent = PaymentIntent.objects.create(
            user=request.user,
            kind=PaymentIntent.Kind.WITHDRAWAL,
            amount_cents=amount,
            currency=settings.DEFAULT_CURRENCY,
            status=PaymentIntent.Status.PENDING,
            processor=result.processor,
            processor_ref=result.processor_ref,
            payout_method=method,
            requires_admin_review=True,
            idempotency_key=idem,
            meta=result.raw or {},
        )
        debit_available(
            request.user,
            amount,
            tx_type=BalanceTransaction.Type.WITHDRAWAL,
            destination_label=f"{method.label} — {method.account_ref[-4:]}",
            hold=True,
            payment_intent=intent,
            idempotency_key=f"wdr-hold-{intent.id}",
        )
        _emit_withdrawal_submitted(request.user, intent, ser.validated_data.get("role"))
        return Response(PaymentIntentSerializer(intent).data, status=status.HTTP_201_CREATED)


class PaymentDetailView(generics.RetrieveAPIView):
    serializer_class = PaymentIntentSerializer

    def get_queryset(self):
        qs = PaymentIntent.objects.all()
        if getattr(self.request.user, "is_admin", False):
            return qs
        return qs.filter(user=self.request.user)


class PaymentsWebhookView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        body = request.body
        headers = {k: v for k, v in request.headers.items()}
        if not payment_util.verify_webhook_signature(headers, body):
            return Response({"detail": "Invalid signature."}, status=401)
        event = payment_util.parse_webhook(headers, body)
        intent = PaymentIntent.objects.filter(processor_ref=event.processor_ref).first()
        if not intent and event.processor_ref:
            # Transfer refs are often `{original}_xfer`
            base = event.processor_ref.removesuffix("_xfer")
            intent = PaymentIntent.objects.filter(processor_ref=base).first()
            if not intent:
                intent = PaymentIntent.objects.filter(meta__transfer_ref=event.processor_ref).first()
        if not intent:
            return Response({"ok": True, "detail": "unknown_ref"})

        if event.amount_cents is not None and event.amount_cents != intent.amount_cents:
            return Response({"detail": "Amount mismatch."}, status=400)
        if event.currency and str(event.currency).upper() != str(intent.currency).upper():
            return Response({"detail": "Currency mismatch."}, status=400)

        with transaction.atomic():
            intent = PaymentIntent.objects.select_for_update().get(pk=intent.pk)
            if event.status == "successful":
                if intent.kind == PaymentIntent.Kind.DEPOSIT:
                    _settle_deposit(intent)
                elif intent.kind in (
                    PaymentIntent.Kind.WITHDRAWAL,
                    PaymentIntent.Kind.INVOICE_PAYOUT,
                ):
                    if intent.status in (
                        PaymentIntent.Status.PENDING,
                        PaymentIntent.Status.PROCESSING,
                    ):
                        intent.status = PaymentIntent.Status.SUCCESSFUL
                        intent.settled_at = timezone.now()
                        intent.save(update_fields=["status", "settled_at", "updated_at"])
                        release_hold_for_intent(intent)
                        if intent.kind == PaymentIntent.Kind.INVOICE_PAYOUT and intent.invoice_id:
                            from invoices.services import mark_invoice_payout_settled

                            mark_invoice_payout_settled(intent.invoice)
                        _emit_withdrawal_decided(intent.user, intent, approved=True)
            elif event.status == "rejected":
                if intent.kind == PaymentIntent.Kind.DEPOSIT and intent.status != PaymentIntent.Status.SUCCESSFUL:
                    intent.status = PaymentIntent.Status.REJECTED
                    intent.save(update_fields=["status", "updated_at"])
                elif intent.kind in (
                    PaymentIntent.Kind.WITHDRAWAL,
                    PaymentIntent.Kind.INVOICE_PAYOUT,
                ) and intent.status in (
                    PaymentIntent.Status.PENDING,
                    PaymentIntent.Status.PROCESSING,
                ):
                    intent.status = PaymentIntent.Status.REJECTED
                    intent.save(update_fields=["status", "updated_at"])
                    reject_hold_for_intent(intent)
                    if intent.kind == PaymentIntent.Kind.INVOICE_PAYOUT and intent.invoice_id:
                        from invoices.services import mark_invoice_payout_failed

                        mark_invoice_payout_failed(intent.invoice)
                    _emit_withdrawal_decided(intent.user, intent, approved=False)
        return Response({"ok": True})


class AdminLedgerListView(generics.ListAPIView):
    permission_classes = [IsAdmin]
    serializer_class = PaymentIntentSerializer

    def get_queryset(self):
        return PaymentIntent.objects.filter(
            status__in=[PaymentIntent.Status.PENDING, PaymentIntent.Status.PROCESSING],
            requires_admin_review=True,
        )


class AdminLedgerDecideView(APIView):
    permission_classes = [IsAdmin]

    @transaction.atomic
    def post(self, request, pk):
        ser = LedgerDecideSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        intent = PaymentIntent.objects.select_for_update().get(pk=pk)
        if intent.status != PaymentIntent.Status.PENDING:
            return Response({"detail": "Not pending."}, status=400)
        decision = ser.validated_data["decision"]
        if decision == "approve":
            if intent.kind == PaymentIntent.Kind.DEPOSIT:
                intent.admin_decision = PaymentIntent.AdminDecision.APPROVE
                intent.save(update_fields=["admin_decision", "updated_at"])
                _settle_deposit(intent)
            else:
                try:
                    _approve_payout_intent(intent)
                except Exception as exc:  # noqa: BLE001 — surface transfer errors
                    return Response({"detail": str(exc)}, status=502)
        else:
            intent.status = PaymentIntent.Status.REJECTED
            intent.admin_decision = PaymentIntent.AdminDecision.REJECT
            intent.save(update_fields=["status", "admin_decision", "updated_at"])
            if intent.kind in (
                PaymentIntent.Kind.WITHDRAWAL,
                PaymentIntent.Kind.INVOICE_PAYOUT,
            ):
                reject_hold_for_intent(intent)
                if intent.kind == PaymentIntent.Kind.INVOICE_PAYOUT and intent.invoice_id:
                    from invoices.services import mark_invoice_payout_failed

                    mark_invoice_payout_failed(intent.invoice)
                _emit_withdrawal_decided(intent.user, intent, approved=False)
        intent.refresh_from_db()
        return Response(PaymentIntentSerializer(intent).data)
