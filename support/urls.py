from django.urls import path

from support import views

urlpatterns = [
    path("support/tickets", views.SupportTicketListCreateView.as_view()),
    path("support/tickets/<uuid:pk>", views.SupportTicketDetailView.as_view()),
    path("support/tickets/<uuid:pk>/messages", views.SupportMessageCreateView.as_view()),
    path("support/tickets/<uuid:pk>/close", views.SupportTicketCloseView.as_view()),
    path("support/tickets/<uuid:pk>/reopen", views.SupportTicketReopenView.as_view()),
]
