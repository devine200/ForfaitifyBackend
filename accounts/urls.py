from django.urls import path

from accounts import views

urlpatterns = [
    path("auth/register", views.RegisterView.as_view()),
    path("auth/verify-email", views.VerifyEmailView.as_view()),
    path("auth/resend-otp", views.ResendOtpView.as_view()),
    path("auth/login", views.LoginView.as_view()),
    path("auth/continue-verification", views.ContinueVerificationView.as_view()),
    path("auth/logout", views.LogoutView.as_view()),
    path("auth/refresh", views.RefreshView.as_view()),
    path("auth/forgot-password", views.ForgotPasswordView.as_view()),
    path("auth/verify-reset-otp", views.VerifyResetOtpView.as_view()),
    path("auth/reset-password", views.ResetPasswordView.as_view()),
    path("auth/me", views.MeView.as_view()),
    path("auth/roles", views.AddAccountRoleView.as_view()),
    path("auth/investor-agreement", views.InvestorAgreementView.as_view()),
    path("auth/sessions", views.SessionListView.as_view()),
    path("auth/sessions/<uuid:session_id>", views.SessionRevokeView.as_view()),
    path("me/profile", views.MeView.as_view()),
    path("me/notification-preferences", views.NotificationPreferenceView.as_view()),
]
