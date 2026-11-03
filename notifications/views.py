from django.utils import timezone
from rest_framework import generics
from rest_framework.response import Response
from rest_framework.views import APIView

from notifications.models import Notification
from notifications.serializers import NotificationSerializer


class NotificationListView(generics.ListAPIView):
    serializer_class = NotificationSerializer

    def get_queryset(self):
        return Notification.objects.filter(user=self.request.user)


class NotificationReadView(APIView):
    def post(self, request, pk):
        n = Notification.objects.filter(user=request.user, pk=pk).first()
        if not n:
            return Response({"detail": "Not found."}, status=404)
        n.read_at = timezone.now()
        n.save(update_fields=["read_at", "updated_at"])
        return Response(NotificationSerializer(n).data)


class NotificationReadAllView(APIView):
    def post(self, request):
        Notification.objects.filter(user=request.user, read_at__isnull=True).update(
            read_at=timezone.now()
        )
        return Response({"detail": "All marked read."})
