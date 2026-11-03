from rest_framework import serializers

from notifications.models import Notification


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = (
            "id",
            "role_scope",
            "category",
            "kind",
            "title",
            "body",
            "urgent",
            "href",
            "read_at",
            "created_at",
        )
