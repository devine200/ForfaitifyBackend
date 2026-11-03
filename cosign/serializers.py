from rest_framework import serializers

from cosign.models import AgreementTemplate, CoSigner, CosignInvite


class AgreementTemplateSerializer(serializers.ModelSerializer):
    class Meta:
        model = AgreementTemplate
        fields = (
            "id",
            "name",
            "body",
            "docusign_template_id",
            "version",
            "is_active",
            "created_at",
        )
        read_only_fields = ("id", "created_at")


class CosignInviteSerializer(serializers.ModelSerializer):
    class Meta:
        model = CosignInvite
        fields = (
            "id",
            "token",
            "invoice",
            "inviter",
            "invitee_email",
            "invitee_name",
            "status",
            "expires_at",
            "created_at",
        )


class CoSignerSerializer(serializers.ModelSerializer):
    class Meta:
        model = CoSigner
        fields = (
            "id",
            "invoice",
            "invite",
            "party_name",
            "party_user",
            "status",
            "docusign_envelope_id",
            "signed_at",
            "created_at",
        )


class InviteCoSignerSerializer(serializers.Serializer):
    email = serializers.EmailField(required=False, allow_blank=True)
    name = serializers.CharField(required=False, allow_blank=True)
    template_id = serializers.UUIDField(required=False)
