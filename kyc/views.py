import json
import logging
import uuid

from django.conf import settings
from django.db import IntegrityError
from django.utils import timezone
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import InvestorProfile, MerchantProfile
from common.permissions import IsAdmin, IsMerchantOrInvestor
from kyc.models import DiditWebhookDelivery, KycRecord, ReviewStatus
from kyc.workflows import KYB_WORKFLOW_ID
from kyc.serializers import (
    AccountStatusSerializer,
    AdminInvestorSerializer,
    AdminKycDecisionSerializer,
    AdminMerchantSerializer,
    KycStatusSerializer,
)
from utils import didit

logger = logging.getLogger("forfaitify.kyc")


class KycSessionView(APIView):
    """Start a Didit hosted session. Documents are collected by Didit, not stored here."""

    permission_classes = [IsMerchantOrInvestor]

    def post(self, request):
        role = str(request.data.get("role") or "").lower()
        if role == "merchant":
            if not request.user.has_merchant:
                return Response({"detail": "Merchant profile required for KYB."}, status=403)
            kind = "kyb"
            workflow_id = KYB_WORKFLOW_ID
        elif role == "investor":
            if not request.user.has_investor:
                return Response({"detail": "Investor profile required for KYC."}, status=403)
            kind = "kyc"
            workflow_id = settings.DIDIT_KYC_WORKFLOW_ID
        else:
            return Response({"detail": "role must be merchant or investor."}, status=400)
        kyc, _ = KycRecord.objects.get_or_create(user=request.user, verification_kind=kind)
        if kyc.is_fully_approved:
            return Response({"detail": "Verification is already approved."}, status=400)
        callback = f"{settings.FRONTEND_BASE_URL.rstrip('/')}/kyc/return"
        try:
            session = didit.create_session(
                user_id=str(request.user.id),
                workflow_id=workflow_id,
                callback_url=callback,
            )
        except RuntimeError as exc:
            return Response({"detail": str(exc)}, status=502)

        update_fields = ["verification_kind", "provider_session_id", "provider_status", "updated_at"]
        if kyc.verification_kind and kyc.verification_kind != kind:
            kyc.admin_status = ReviewStatus.PENDING
            kyc.reviewed_by = None
            kyc.reviewed_at = None
            update_fields.extend(["admin_status", "reviewed_by", "reviewed_at"])
        kyc.verification_kind = kind
        kyc.provider_session_id = session.session_id
        kyc.provider_status = session.status or ReviewStatus.PROCESSING
        kyc.save(update_fields=update_fields)
        return Response(
            {
                "session_id": session.session_id,
                "url": session.url,
                "status": kyc.provider_status,
                "kind": kind,
                "mode": settings.DIDIT_MODE,
            }
        )


class KycStatusView(APIView):
    permission_classes = [IsMerchantOrInvestor]

    def get(self, request):
        role = str(request.query_params.get("role") or "").lower()
        if role == "merchant":
            kind = "kyb"
        elif role == "investor":
            kind = "kyc"
        elif request.user.has_merchant and not request.user.has_investor:
            kind = "kyb"
        elif request.user.has_investor and not request.user.has_merchant:
            kind = "kyc"
        else:
            kind = ""
        kyc = (
            KycRecord.objects.filter(user=request.user, verification_kind=kind).first()
            if kind
            else KycRecord.objects.filter(user=request.user)
            .exclude(verification_kind="")
            .order_by("-updated_at")
            .first()
        )
        if not kyc:
            return Response(
                {
                    "verification_kind": kind,
                    "provider_session_id": "",
                    "provider_status": "pending",
                    "admin_status": "pending",
                    "is_fully_approved": False,
                    "reviewed_at": None,
                    "mode": settings.DIDIT_MODE,
                }
            )
        return Response(KycStatusSerializer(kyc).data)


class DiditWebhookView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        body = request.body
        headers = {k: v for k, v in request.headers.items()}
        if not didit.verify_webhook_signature(headers, body):
            return Response({"detail": "Invalid signature."}, status=401)
        try:
            payload = json.loads(body.decode() or "{}")
        except json.JSONDecodeError:
            return Response({"detail": "Invalid JSON."}, status=400)
        event_id = str(payload.get("event_id") or "")
        if event_id:
            try:
                DiditWebhookDelivery.objects.create(event_id=event_id[:64])
            except IntegrityError:
                return Response({"ok": True})
        event = didit.parse_webhook(body)
        kyc = None
        if event.session_id:
            kyc = KycRecord.objects.filter(provider_session_id=event.session_id).first()
        if not kyc and event.vendor_data:
            try:
                user_id = uuid.UUID(str(event.vendor_data))
            except ValueError:
                logger.warning(
                    "Didit webhook ignored: vendor_data is not a UUID session_id=%s vendor_data=%s status=%s",
                    event.session_id or "-",
                    event.vendor_data,
                    event.review_status,
                )
            else:
                kyc = KycRecord.objects.filter(user_id=user_id).first()
        if kyc:
            kyc.provider_status = event.review_status
            if event.session_id:
                kyc.provider_session_id = event.session_id
            kyc.raw_webhook_payload = event.raw
            kyc.save(
                update_fields=[
                    "provider_session_id",
                    "provider_status",
                    "raw_webhook_payload",
                    "updated_at",
                ]
            )
            from notifications.emit import emit
            from notifications.keys import key

            emit(
                event_type="kyc.status.changed",
                user=kyc.user,
                notify_admins=True,
                notification={
                    "category": "securityAlerts",
                    "kind": "warn",
                    "title": "KYC status updated",
                    "body": f"Identity review status is now {event.review_status}.",
                    "href": "/merchant/settings",
                },
                invalidate=[
                    key("kyc"),
                    key("adminMerchants"),
                    key("adminInvestors"),
                    key("notifications"),
                ],
                email=False,
            )
        else:
            logger.info(
                "Didit webhook acknowledged with no matching KYC record session_id=%s vendor_data=%s status=%s",
                event.session_id or "-",
                event.vendor_data or "-",
                event.review_status,
            )
        return Response({"ok": True})


class AdminMerchantListView(generics.ListAPIView):
    permission_classes = [IsAdmin]
    serializer_class = AdminMerchantSerializer

    def get_queryset(self):
        qs = MerchantProfile.objects.select_related("user").prefetch_related("user__kyc_records")
        status_q = self.request.query_params.get("account_status")
        if status_q:
            qs = qs.filter(account_status=status_q)
        return qs


class AdminMerchantDetailView(generics.RetrieveAPIView):
    permission_classes = [IsAdmin]
    serializer_class = AdminMerchantSerializer
    queryset = MerchantProfile.objects.select_related("user").prefetch_related("user__kyc_records")


class AdminMerchantKycView(APIView):
    permission_classes = [IsAdmin]

    def patch(self, request, pk):
        ser = AdminKycDecisionSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        merchant = MerchantProfile.objects.select_related("user").get(pk=pk)
        kyc, _ = KycRecord.objects.get_or_create(user=merchant.user, verification_kind="kyb")
        kyc.admin_status = ser.validated_data["admin_status"]
        kyc.reviewed_by = request.user
        kyc.reviewed_at = timezone.now()
        kyc.save()
        from notifications.emit import emit
        from notifications.keys import key

        emit(
            event_type="kyc.status.changed",
            user=merchant.user,
            notify_admins=True,
            role_scope="merchant",
            notification={
                "category": "securityAlerts",
                "kind": "send",
                "title": "KYC decision updated",
                "body": f"Admin status is now {kyc.admin_status}.",
                "href": "/merchant/settings",
            },
            invalidate=[
                key("kyc"),
                key("adminMerchant", str(merchant.id)),
                key("adminMerchants"),
                key("notifications"),
            ],
            email=False,
        )
        return Response(KycStatusSerializer(kyc).data)


class AdminMerchantStatusView(APIView):
    permission_classes = [IsAdmin]

    def patch(self, request, pk):
        ser = AccountStatusSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        merchant = MerchantProfile.objects.get(pk=pk)
        merchant.account_status = ser.validated_data["account_status"]
        merchant.save(update_fields=["account_status", "updated_at"])
        return Response(AdminMerchantSerializer(merchant).data)


class AdminInvestorListView(generics.ListAPIView):
    permission_classes = [IsAdmin]
    serializer_class = AdminInvestorSerializer

    def get_queryset(self):
        return InvestorProfile.objects.select_related("user").prefetch_related("user__kyc_records")


class AdminInvestorDetailView(generics.RetrieveAPIView):
    permission_classes = [IsAdmin]
    serializer_class = AdminInvestorSerializer
    queryset = InvestorProfile.objects.select_related("user").prefetch_related("user__kyc_records")


class AdminInvestorKycView(APIView):
    permission_classes = [IsAdmin]

    def patch(self, request, pk):
        ser = AdminKycDecisionSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        investor = InvestorProfile.objects.select_related("user").get(pk=pk)
        kyc, _ = KycRecord.objects.get_or_create(user=investor.user, verification_kind="kyc")
        kyc.admin_status = ser.validated_data["admin_status"]
        kyc.reviewed_by = request.user
        kyc.reviewed_at = timezone.now()
        kyc.save()
        from notifications.emit import emit
        from notifications.keys import key

        emit(
            event_type="kyc.status.changed",
            user=investor.user,
            notify_admins=True,
            role_scope="investor",
            notification={
                "category": "securityAlerts",
                "kind": "send",
                "title": "KYC decision updated",
                "body": f"Admin status is now {kyc.admin_status}.",
                "href": "/investor/settings",
            },
            invalidate=[
                key("kyc"),
                key("adminInvestor", str(investor.id)),
                key("adminInvestors"),
                key("notifications"),
            ],
            email=False,
        )
        return Response(KycStatusSerializer(kyc).data)


class AdminInvestorStatusView(APIView):
    permission_classes = [IsAdmin]

    def patch(self, request, pk):
        ser = AccountStatusSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        investor = InvestorProfile.objects.get(pk=pk)
        investor.account_status = ser.validated_data["account_status"]
        investor.save(update_fields=["account_status", "updated_at"])
        return Response(AdminInvestorSerializer(investor).data)
