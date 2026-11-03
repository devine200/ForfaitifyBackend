from rest_framework import generics
from rest_framework.response import Response
from rest_framework.views import APIView

from balances.models import BalanceTransaction
from balances.serializers import BalanceSerializer, BalanceTransactionSerializer
from balances.services import get_or_create_balance
from common.permissions import IsMerchantOrInvestor


class BalanceView(APIView):
    permission_classes = [IsMerchantOrInvestor]

    def get(self, request):
        balance = get_or_create_balance(request.user)
        return Response(BalanceSerializer(balance).data)


class BalanceTransactionListView(generics.ListAPIView):
    permission_classes = [IsMerchantOrInvestor]
    serializer_class = BalanceTransactionSerializer

    def get_queryset(self):
        qs = BalanceTransaction.objects.filter(balance__user=self.request.user)
        tx_type = self.request.query_params.get("type")
        status_q = self.request.query_params.get("status")
        if tx_type:
            qs = qs.filter(type=tx_type)
        if status_q:
            qs = qs.filter(status=status_q)
        return qs
