from django.urls import path

from pools import views

urlpatterns = [
    path("pools", views.PoolListView.as_view()),
    path("pools/custom", views.CustomPoolCreateView.as_view()),
    path("pools/<uuid:pk>", views.PoolDetailView.as_view()),
    path("pools/<uuid:pk>/update", views.CustomPoolUpdateView.as_view()),
    path("pools/<uuid:pk>/deposits", views.PoolDepositView.as_view()),
    path("pools/<uuid:pk>/withdrawals", views.PoolWithdrawalCreateView.as_view()),
    path("pools/<uuid:pk>/withdrawals/list", views.PoolWithdrawalListView.as_view()),
    path("pools/<uuid:pool_id>/withdrawals/<uuid:pk>/settle", views.PoolWithdrawalSettleView.as_view()),
    path("admin/pools", views.AdminPoolCreateView.as_view()),
    path("admin/pools/<uuid:pk>", views.AdminPoolUpdateView.as_view()),
    path("admin/pools/<uuid:pk>/close", views.AdminPoolCloseView.as_view()),
    path("admin/pool-withdrawals/<uuid:pk>/decide", views.AdminPoolWithdrawalDecideView.as_view()),
]
