import secrets

from django.utils import timezone
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from common.permissions import IsAdmin, IsMerchantOrInvestor
from notifications.emit import emit, ticket_room
from notifications.keys import key
from support.models import SupportMessage, SupportTicket
from support.serializers import (
    CreateTicketSerializer,
    MessageCreateSerializer,
    SupportMessageSerializer,
    SupportTicketSerializer,
)


def _emit_support(ticket, *, title: str, body: str, users):
    emit(
        event_type="support.message.created",
        users=users,
        user=ticket.requester,
        notify_admins=True,
        role_scope=ticket.role_scope,
        notification={
            "category": "securityAlerts",
            "kind": "send",
            "title": title,
            "body": body,
            "href": f"/{ticket.role_scope}/support/{ticket.id}",
        },
        invalidate=[
            key("supportTickets"),
            key("supportTicket", str(ticket.id)),
            key("notifications"),
        ],
        room=ticket_room(ticket.id),
        email=False,
    )


class SupportTicketListCreateView(APIView):
    def get(self, request):
        if getattr(request.user, "is_admin", False):
            qs = SupportTicket.objects.all()
        else:
            qs = SupportTicket.objects.filter(requester=request.user)
        return Response(SupportTicketSerializer(qs, many=True, context={"request": request}).data)

    def post(self, request):
        if getattr(request.user, "is_admin", False):
            return Response({"detail": "Admins cannot open user tickets here."}, status=400)
        if not IsMerchantOrInvestor().has_permission(request, self):
            return Response({"detail": "Merchant or investor required."}, status=403)
        ser = CreateTicketSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        ticket = SupportTicket.objects.create(
            requester=request.user,
            role_scope=data["role_scope"],
            title=data["title"],
            topic=data["topic"],
            code=f"TK-{secrets.token_hex(3).upper()}",
            last_message_at=timezone.now(),
        )
        SupportMessage.objects.create(ticket=ticket, author=request.user, body=data["body"])
        _emit_support(
            ticket,
            title=f"Support ticket {ticket.code} opened",
            body=ticket.title,
            users=[request.user],
        )
        return Response(
            SupportTicketSerializer(ticket, context={"request": request}).data,
            status=201,
        )


class SupportTicketDetailView(generics.RetrieveAPIView):
    serializer_class = SupportTicketSerializer

    def get_queryset(self):
        if getattr(self.request.user, "is_admin", False):
            return SupportTicket.objects.prefetch_related("messages")
        return SupportTicket.objects.filter(requester=self.request.user).prefetch_related("messages")


class SupportMessageCreateView(APIView):
    def post(self, request, pk):
        ticket = SupportTicket.objects.filter(pk=pk).first()
        if not ticket:
            return Response({"detail": "Not found."}, status=404)
        if not request.user.is_admin and ticket.requester_id != request.user.id:
            return Response({"detail": "Forbidden."}, status=403)
        if ticket.status == SupportTicket.Status.CLOSED:
            return Response({"detail": "Ticket closed."}, status=400)
        ser = MessageCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        msg = SupportMessage.objects.create(
            ticket=ticket,
            author=request.user,
            body=ser.validated_data["body"],
        )
        ticket.last_message_at = timezone.now()
        ticket.status = SupportTicket.Status.ACTIVE
        ticket.save(update_fields=["last_message_at", "status", "updated_at"])
        _emit_support(
            ticket,
            title=f"New reply on {ticket.code}",
            body=ser.validated_data["body"][:160],
            users=[ticket.requester],
        )
        return Response(SupportMessageSerializer(msg, context={"request": request}).data, status=201)


class SupportTicketCloseView(APIView):
    def post(self, request, pk):
        ticket = SupportTicket.objects.filter(pk=pk).first()
        if not ticket:
            return Response({"detail": "Not found."}, status=404)
        if not request.user.is_admin and ticket.requester_id != request.user.id:
            return Response({"detail": "Forbidden."}, status=403)
        ticket.status = SupportTicket.Status.CLOSED
        ticket.closed_at = timezone.now()
        ticket.save(update_fields=["status", "closed_at", "updated_at"])
        return Response(SupportTicketSerializer(ticket, context={"request": request}).data)


class SupportTicketReopenView(APIView):
    permission_classes = [IsAdmin]

    def post(self, request, pk):
        ticket = SupportTicket.objects.get(pk=pk)
        ticket.status = SupportTicket.Status.ACTIVE
        ticket.closed_at = None
        ticket.save(update_fields=["status", "closed_at", "updated_at"])
        return Response(SupportTicketSerializer(ticket, context={"request": request}).data)
