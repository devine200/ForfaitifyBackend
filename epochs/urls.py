from django.urls import path

from epochs import views

urlpatterns = [
    path("pools/<uuid:pk>/epochs", views.PoolEpochListView.as_view()),
    path("pools/<uuid:pk>/epochs/current", views.PoolCurrentEpochView.as_view()),
    path("epochs/<uuid:pk>", views.EpochDetailView.as_view()),
    path("admin/epochs/<uuid:pk>/advance", views.AdminEpochAdvanceView.as_view()),
]
