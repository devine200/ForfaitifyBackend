from rest_framework import generics
from rest_framework.response import Response
from rest_framework.views import APIView

from common.permissions import IsAdmin
from epochs.events import emit_epoch_advanced
from epochs.models import Epoch
from epochs.serializers import EpochSerializer


class PoolEpochListView(generics.ListAPIView):
    serializer_class = EpochSerializer

    def get_queryset(self):
        return Epoch.objects.filter(pool_id=self.kwargs["pk"])


class PoolCurrentEpochView(APIView):
    def get(self, request, pk):
        epoch = (
            Epoch.objects.filter(pool_id=pk)
            .exclude(state=Epoch.State.CLOSED)
            .order_by("-index")
            .first()
        )
        if not epoch:
            return Response({"detail": "No active epoch."}, status=404)
        return Response(EpochSerializer(epoch).data)


class EpochDetailView(generics.RetrieveAPIView):
    serializer_class = EpochSerializer
    queryset = Epoch.objects.all()


class AdminEpochAdvanceView(APIView):
    permission_classes = [IsAdmin]

    def post(self, request, pk):
        epoch = Epoch.objects.get(pk=pk)
        order = [
            Epoch.State.FUNDING_OPEN,
            Epoch.State.CAPITAL_DEPLOYED,
            Epoch.State.MATURED,
            Epoch.State.RETURNS_DISTRIBUTED,
            Epoch.State.CLOSED,
        ]
        try:
            idx = order.index(epoch.state)
        except ValueError:
            return Response({"detail": "Unknown state."}, status=400)
        if idx >= len(order) - 1:
            return Response({"detail": "Already closed."}, status=400)
        epoch.state = order[idx + 1]
        epoch.save(update_fields=["state", "updated_at"])
        if epoch.state == Epoch.State.CLOSED:
            from pools.services import ensure_current_epoch

            ensure_current_epoch(epoch.pool)
        emit_epoch_advanced(epoch)
        return Response(EpochSerializer(epoch).data)
