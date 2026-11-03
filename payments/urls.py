from django.urls import path

from payments import views

urlpatterns = [
    path("payout-methods", views.PayoutMethodListCreateView.as_view()),
    path("payout-methods/<uuid:pk>", views.PayoutMethodDeleteView.as_view()),
    path("payments/deposits", views.DepositView.as_view()),
    path("payments/withdrawals", views.WithdrawalView.as_view()),
    path("payments/<uuid:pk>", views.PaymentDetailView.as_view()),
    path("webhooks/payments", views.PaymentsWebhookView.as_view()),
    path("admin/ledger", views.AdminLedgerListView.as_view()),
    path("admin/ledger/<uuid:pk>/decide", views.AdminLedgerDecideView.as_view()),
]
