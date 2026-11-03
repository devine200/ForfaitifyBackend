import secrets

from django.contrib.auth import get_user_model
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from admin_ops.models import AdminInvite, PaymentGatewayConfig, PlatformFees
from admin_ops.serializers import (
    AcceptInviteSerializer,
    AdminInviteCreateSerializer,
    AdminInviteSerializer,
    PaymentGatewaySerializer,
    PlatformFeesSerializer,
)
from balances.services import get_or_create_balance
from common.permissions import IsAdmin
from kyc.models import KycRecord, ReviewStatus

User = get_user_model()


class FeesView(APIView):
    permission_classes = [IsAdmin]

    def get(self, request):
        fees = PlatformFees.objects.order_by("-effective_at").first()
        if not fees:
            fees = PlatformFees.objects.create()
        return Response(PlatformFeesSerializer(fees).data)

    def put(self, request):
        fees = PlatformFees.objects.create(
            platform_fee_bps=int(request.data.get("platform_fee_bps", 250)),
            withdrawal_fee_bps=int(request.data.get("withdrawal_fee_bps", 350)),
            lateness_fee_bps=int(request.data.get("lateness_fee_bps", 1050)),
        )
        return Response(PlatformFeesSerializer(fees).data)


class GatewayListView(generics.ListAPIView):
    permission_classes = [IsAdmin]
    serializer_class = PaymentGatewaySerializer
    queryset = PaymentGatewayConfig.objects.all()


class GatewayPrimaryView(APIView):
    permission_classes = [IsAdmin]

    def post(self, request, pk):
        PaymentGatewayConfig.objects.update(is_primary=False, status=PaymentGatewayConfig.Status.INACTIVE)
        gw = PaymentGatewayConfig.objects.get(pk=pk)
        gw.is_primary = True
        gw.status = PaymentGatewayConfig.Status.ACTIVE
        gw.detail = "Primary gateway"
        gw.save()
        return Response(PaymentGatewaySerializer(gw).data)


class GatewayDisableView(APIView):
    permission_classes = [IsAdmin]

    def post(self, request, pk):
        gw = PaymentGatewayConfig.objects.get(pk=pk)
        gw.is_primary = False
        gw.status = PaymentGatewayConfig.Status.INACTIVE
        gw.detail = "Disabled"
        gw.save()
        return Response(PaymentGatewaySerializer(gw).data)


class StaffListView(APIView):
    """Active admin users plus outstanding invites."""

    permission_classes = [IsAdmin]

    def get(self, request):
        admins = [
            {
                "id": str(user.id),
                "email": user.email,
                "full_name": user.full_name,
                "status": "active" if user.is_active else "disabled",
                "kind": "user",
                "created_at": user.created_at,
            }
            for user in User.objects.filter(is_admin=True).order_by("-created_at")
        ]
        invites = [
            {
                "id": str(invite.id),
                "email": invite.email,
                "full_name": invite.full_name,
                "status": invite.status,
                "kind": "invite",
                "created_at": invite.created_at,
            }
            for invite in AdminInvite.objects.exclude(status=AdminInvite.Status.ACCEPTED).order_by(
                "-created_at"
            )
        ]
        return Response({"admins": admins, "invites": invites})


class StaffInviteView(APIView):
    permission_classes = [IsAdmin]

    def post(self, request):
        ser = AdminInviteCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        invite = AdminInvite.objects.create(
            email=ser.validated_data["email"].strip().lower(),
            full_name=ser.validated_data.get("full_name", ""),
            invited_by=request.user,
            token=secrets.token_urlsafe(24),
        )
        return Response(AdminInviteSerializer(invite).data, status=201)


class StaffDisableView(APIView):
    permission_classes = [IsAdmin]

    def post(self, request, pk):
        invite = AdminInvite.objects.get(pk=pk)
        invite.status = AdminInvite.Status.DISABLED
        invite.save(update_fields=["status", "updated_at"])
        User.objects.filter(email__iexact=invite.email).update(is_admin=False, is_active=False)
        return Response(AdminInviteSerializer(invite).data)


class AcceptInviteView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        ser = AcceptInviteSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        invite = AdminInvite.objects.filter(
            token=ser.validated_data["token"],
            status=AdminInvite.Status.INVITED,
        ).first()
        if not invite:
            return Response({"detail": "Invalid invite."}, status=400)
        user, _ = User.objects.get_or_create(
            email=invite.email,
            defaults={
                "full_name": ser.validated_data.get("full_name") or invite.full_name,
                "is_active": True,
                "is_admin": True,
                "is_staff": True,
                "email_verified": True,
            },
        )
        user.set_password(ser.validated_data["password"])
        user.is_admin = True
        user.is_staff = True
        user.is_active = True
        user.email_verified = True
        user.save()
        KycRecord.objects.get_or_create(
            user=user,
            verification_kind="",
            defaults={
                "provider_status": ReviewStatus.APPROVED,
                "admin_status": ReviewStatus.APPROVED,
            },
        )
        get_or_create_balance(user)
        invite.status = AdminInvite.Status.ACCEPTED
        invite.save(update_fields=["status", "updated_at"])
        return Response({"detail": "Admin account ready.", "email": user.email})


class ContactView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        # Placeholder inbox — accept and acknowledge
        email = request.data.get("email")
        message = request.data.get("message")
        if not email or not message:
            return Response({"detail": "email and message required."}, status=400)
        return Response({"detail": "Message received."}, status=201)
