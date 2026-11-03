from django.urls import path

from notifications import views

urlpatterns = [
    path("notifications", views.NotificationListView.as_view()),
    path("notifications/<uuid:pk>/read", views.NotificationReadView.as_view()),
    path("notifications/read-all", views.NotificationReadAllView.as_view()),
]
