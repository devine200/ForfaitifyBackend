from rest_framework import serializers

from epochs.models import Epoch


class EpochSerializer(serializers.ModelSerializer):
    class Meta:
        model = Epoch
        fields = (
            "id",
            "pool",
            "index",
            "starts_at",
            "ends_at",
            "withdrawal_window_start",
            "withdrawal_window_end",
            "state",
            "created_at",
        )
