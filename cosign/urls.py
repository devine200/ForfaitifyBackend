from django.urls import path

from cosign import views

urlpatterns = [
    path("admin/agreement-templates", views.AgreementTemplateListCreateView.as_view()),
    path("admin/agreement-templates/<uuid:pk>", views.AgreementTemplateUpdateView.as_view()),
    path("merchant/invoices/<uuid:pk>/co-signers", views.InviteCoSignerView.as_view()),
    path("invites/co-sign/<str:token>", views.PublicCosignInviteView.as_view()),
    path("cosign/requests", views.CosignRequestListView.as_view()),
    path("cosign/requests/<uuid:pk>/start-signing", views.StartSigningView.as_view()),
    path("webhooks/docusign", views.DocuSignWebhookView.as_view()),
]
