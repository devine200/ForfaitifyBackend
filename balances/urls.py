from django.urls import path

from balances import views

urlpatterns = [
    path("balance", views.BalanceView.as_view()),
    path("balance/transactions", views.BalanceTransactionListView.as_view()),
]
