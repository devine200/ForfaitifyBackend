from rest_framework import serializers

from support.models import SupportMessage, SupportTicket


class SupportMessageSerializer(serializers.ModelSerializer):
    author_email = serializers.EmailField(source="author.email", read_only=True)
    mine = serializers.SerializerMethodField()

    class Meta:
        model = SupportMessage
        fields = ("id", "ticket", "author", "author_email", "body", "mine", "created_at")
        read_only_fields = ("id", "author", "ticket", "created_at")

    def get_mine(self, obj):
        request = self.context.get("request")
        return bool(request and obj.author_id == request.user.id)


class SupportTicketSerializer(serializers.ModelSerializer):
    messages = SupportMessageSerializer(many=True, read_only=True)

    class Meta:
        model = SupportTicket
        fields = (
            "id",
            "code",
            "role_scope",
            "title",
            "topic",
            "status",
            "closed_at",
            "last_message_at",
            "messages",
            "created_at",
        )


class CreateTicketSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=255)
    topic = serializers.CharField(max_length=64)
    body = serializers.CharField()
    role_scope = serializers.ChoiceField(choices=["merchant", "investor"])


class MessageCreateSerializer(serializers.Serializer):
    body = serializers.CharField()
