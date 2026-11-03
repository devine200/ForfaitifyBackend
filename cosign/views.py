import secrets
from datetime import timedelta

from django.utils import timezone
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from common.permissions import IsAdmin, IsMerchant
from cosign.models import AgreementTemplate, CoSigner, CosignInvite
from cosign.serializers import (
    AgreementTemplateSerializer,
    CoSignerSerializer,
    CosignInviteSerializer,
    InviteCoSignerSerializer,
)
from invoices.models import Invoice
from notifications.emit import emit, invoice_room
from notifications.keys import key
from utils import docusign


class AgreementTemplateListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAdmin]
    serializer_class = AgreementTemplateSerializer
    queryset = AgreementTemplate.objects.all()

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class AgreementTemplateUpdateView(generics.UpdateAPIView):
    permission_classes = [IsAdmin]
    serializer_class = AgreementTemplateSerializer
    queryset = AgreementTemplate.objects.all()


class InviteCoSignerView(APIView):
    permission_classes = [IsMerchant]

    def post(self, request, pk):
        ser = InviteCoSignerSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        invoice = Invoice.objects.get(pk=pk, merchant=request.user.merchant_profile)
        data = ser.validated_data
        if not data.get("email") and not data.get("name"):
            return Response({"detail": "Provide email or name."}, status=400)

        token = secrets.token_urlsafe(24)
        invite = CosignInvite.objects.create(
            token=token,
            invoice=invoice,
            inviter=request.user.merchant_profile,
            invitee_email=data.get("email", ""),
            invitee_name=data.get("name", ""),
            expires_at=timezone.now() + timedelta(days=14),
        )
        template = None
        if data.get("template_id"):
            template = AgreementTemplate.objects.filter(id=data["template_id"]).first()
        else:
            template = AgreementTemplate.objects.filter(is_active=True).order_by("-version").first()

        envelope = docusign.create_envelope(
            template_id=template.docusign_template_id if template else None,
            signer_email=invite.invitee_email or "signer@example.com",
            signer_name=invite.invitee_name or "Co-signer",
            document_name=f"Co-sign {invoice.code}",
            return_url="https://app.forfaitify.local/cosign/complete",
        )
        cosigner = CoSigner.objects.create(
            invoice=invoice,
            invite=invite,
            party_name=invite.invitee_name or invite.invitee_email or "Co-signer",
            docusign_envelope_id=envelope.envelope_id,
        )
        invite_href = f"/invite/co-sign/{invite.token}"
        emit(
            event_type="cosign.invite.sent",
            user=request.user,
            role_scope="merchant",
            notification={
                "category": "invoiceUpdates",
                "kind": "warn",
                "title": f"Co-sign invite sent for {invoice.code}",
                "body": f"Waiting on {invite.invitee_name or invite.invitee_email or 'co-signer'}.",
                "href": f"/merchant/invoices/{invoice.id}",
            },
            invalidate=[
                key("merchantInvoice", str(invoice.id)),
                key("merchantInvoices"),
                key("cosignRequests"),
                key("notifications"),
            ],
            room=invoice_room(invoice.id),
            email="cosign" if invite.invitee_email else False,
            email_to=invite.invitee_email or None,
            idempotency_key=f"email:cosign.invite.sent:{invite.id}",
            email_context={
                "title": f"Co-sign requested for {invoice.code}",
                "body": (
                    f"{invite.inviter.business_name or request.user.full_name} invited you "
                    f"to co-sign a receivable on Forfaitify."
                ),
                "href": invite_href,
                "invoice_code": invoice.code,
                "inviter_name": invite.inviter.business_name or request.user.full_name,
                "invitee_name": invite.invitee_name,
                "cta_label": "Review and sign",
            },
        )
        return Response(
            {
                "invite": CosignInviteSerializer(invite).data,
                "cosigner": CoSignerSerializer(cosigner).data,
                "signing_url": envelope.signing_url,
            },
            status=status.HTTP_201_CREATED,
        )


class PublicCosignInviteView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request, token):
        invite = CosignInvite.objects.select_related("invoice", "inviter").filter(token=token).first()
        if not invite:
            return Response({"detail": "Invite not found."}, status=404)
        inv = invite.invoice
        return Response(
            {
                "invite_id": str(invite.id),
                "token": invite.token,
                "status": invite.status,
                "invitee_name": invite.invitee_name,
                "invitee_email": invite.invitee_email,
                "inviter_name": invite.inviter.business_name or invite.inviter.user.full_name,
                "invoice": {
                    "id": str(inv.id),
                    "code": inv.code,
                    "name": inv.name,
                    "loan_amount_cents": inv.loan_amount_cents,
                    "due_date": inv.due_date,
                },
            }
        )


class CosignRequestListView(generics.ListAPIView):
    permission_classes = [IsMerchant]
    serializer_class = CoSignerSerializer

    def get_queryset(self):
        return CoSigner.objects.filter(
            status=CoSigner.Status.PENDING,
            party_user=self.request.user,
        ) | CoSigner.objects.filter(
            status=CoSigner.Status.PENDING,
            invite__invitee_email__iexact=self.request.user.email,
        )


class StartSigningView(APIView):
    permission_classes = [IsMerchant]

    def post(self, request, pk):
        cosigner = CoSigner.objects.select_related("invite", "invoice").get(pk=pk)
        envelope = docusign.create_envelope(
            template_id=None,
            signer_email=request.user.email,
            signer_name=request.user.full_name or request.user.email,
            document_name=f"Co-sign {cosigner.invoice.code}",
            return_url="https://app.forfaitify.local/cosign/complete",
        )
        cosigner.docusign_envelope_id = envelope.envelope_id
        cosigner.party_user = request.user
        cosigner.save(update_fields=["docusign_envelope_id", "party_user", "updated_at"])
        return Response({"signing_url": envelope.signing_url, "envelope_id": envelope.envelope_id})


class DocuSignWebhookView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        body = request.body
        headers = {k: v for k, v in request.headers.items()}
        if not docusign.verify_webhook_signature(headers, body):
            return Response({"detail": "Invalid signature."}, status=401)
        event = docusign.parse_webhook(headers, body)
        cosigner = CoSigner.objects.filter(docusign_envelope_id=event.envelope_id).first()
        if cosigner:
            if event.status == "signed":
                cosigner.status = CoSigner.Status.SIGNED
                cosigner.signed_at = timezone.now()
            elif event.status == "rejected":
                cosigner.status = CoSigner.Status.REJECTED
            cosigner.save()
            if cosigner.invite_id:
                cosigner.invite.status = (
                    CosignInvite.Status.ACCEPTED
                    if event.status == "signed"
                    else CosignInvite.Status.PENDING
                )
                cosigner.invite.save(update_fields=["status", "updated_at"])
            merchant_user = cosigner.invoice.merchant.user
            emit(
                event_type="cosign.status.changed",
                user=merchant_user,
                role_scope="merchant",
                notification={
                    "category": "invoiceUpdates",
                    "kind": "send" if event.status == "signed" else "alert",
                    "title": f"Co-sign {event.status} · {cosigner.invoice.code}",
                    "body": f"{cosigner.party_name} {event.status} the agreement.",
                    "urgent": event.status == "rejected",
                    "href": f"/merchant/invoices/{cosigner.invoice_id}",
                },
                invalidate=[
                    key("merchantInvoice", str(cosigner.invoice_id)),
                    key("merchantInvoices"),
                    key("cosignRequests"),
                    key("notifications"),
                ],
                room=invoice_room(cosigner.invoice_id),
                email="cosign",
                idempotency_key=f"email:cosign.status.changed:{cosigner.id}:{event.status}",
                email_context={
                    "invoice_code": cosigner.invoice.code,
                    "inviter_name": cosigner.party_name,
                    "status": event.status,
                },
            )
        return Response({"ok": True})
