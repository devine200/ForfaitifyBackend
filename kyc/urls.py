from django.urls import path

from kyc import views

urlpatterns = [
    path("kyc/session", views.KycSessionView.as_view()),
    path("kyc/status", views.KycStatusView.as_view()),
    path("webhooks/didit", views.DiditWebhookView.as_view()),
    path("admin/merchants", views.AdminMerchantListView.as_view()),
    path("admin/merchants/<uuid:pk>", views.AdminMerchantDetailView.as_view()),
    path("admin/merchants/<uuid:pk>/kyc", views.AdminMerchantKycView.as_view()),
    path("admin/merchants/<uuid:pk>/status", views.AdminMerchantStatusView.as_view()),
    path("admin/investors", views.AdminInvestorListView.as_view()),
    path("admin/investors/<uuid:pk>", views.AdminInvestorDetailView.as_view()),
    path("admin/investors/<uuid:pk>/kyc", views.AdminInvestorKycView.as_view()),
    path("admin/investors/<uuid:pk>/status", views.AdminInvestorStatusView.as_view()),
]
