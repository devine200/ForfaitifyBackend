from django.urls import path

from admin_ops import views

urlpatterns = [
    path("admin/settings/fees", views.FeesView.as_view()),
    path("admin/settings/gateways", views.GatewayListView.as_view()),
    path("admin/settings/gateways/<uuid:pk>/primary", views.GatewayPrimaryView.as_view()),
    path("admin/settings/gateways/<uuid:pk>/disable", views.GatewayDisableView.as_view()),
    path("admin/staff", views.StaffListView.as_view()),
    path("admin/staff/invite", views.StaffInviteView.as_view()),
    path("admin/staff/<uuid:pk>/disable", views.StaffDisableView.as_view()),
    path("admin/staff/accept-invite", views.AcceptInviteView.as_view()),
    path("public/contact", views.ContactView.as_view()),
]
